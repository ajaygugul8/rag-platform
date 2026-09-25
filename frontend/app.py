"""
Modern RAG Platform - Streamlit frontend.

Design principles:
  1. The answer is the product. Reading experience comes first.
  2. Progress is visible. RAG takes 30-60s; the user sees what's happening.
  3. Citations are first-class. Numbered margin notes, not a buried expander.
  4. Empty states guide the user with one-click examples, not silence.
  5. Navigation stays out of the way of the primary task.

Pure HTTP client against the FastAPI backend. No app.* imports.

PERSISTENCE NOTE (this is the fix for "conversations disappear on
refresh"): the sidebar conversation list used to live only in
st.session_state, which Streamlit throws away on every page refresh /
new browser tab. Conversations are now persisted server-side in
Postgres (the same database that already backs everything else in this
project -- see backend/app/api/conversations.py and the
ChatMessage model). On startup this file fetches the conversation list
from GET /conversations; opening a conversation lazily fetches its full
message history from GET /conversations/{session_id}. Nothing is kept
in browser storage, which also means conversations survive a full
container restart and are visible from any browser hitting the same
backend -- consistent with "Postgres is the only stateful service" for
this project.

ENCODING NOTE: this file is pure ASCII on purpose. Non-ASCII characters
(em dashes, curly quotes, unicode icons) in Python source have
repeatedly caused UnicodeDecodeError/SyntaxError on Windows when saved
by an editor that defaults to cp1252 instead of UTF-8. HTML entities
like &#10003; are used for symbols instead - they render identically in
the browser with no encoding risk.
"""

import html
import json as _json
import os
import sys
import threading
import time
import uuid
from collections import defaultdict
from datetime import datetime, date
from pathlib import Path

import requests
import streamlit as st

SCRIPT_DIR = Path(__file__).resolve().parent if "__file__" in globals() else Path.cwd()
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from styles import inject_css

API_BASE = os.environ.get("RAG_API_BASE", "http://localhost:8000")
DEFAULT_TOKEN = os.environ.get("RAG_API_TOKEN", "change-me-dev-token")


# ============================================================================
# API HELPERS
# ============================================================================

def api(method: str, path: str, **kwargs):
    headers = kwargs.pop("headers", {})
    headers["Authorization"] = f"Bearer {st.session_state.get('api_token', DEFAULT_TOKEN)}"
    r = requests.request(method, f"{API_BASE}{path}", headers=headers, timeout=300, **kwargs)
    if r.status_code >= 400:
        try:
            detail = r.json().get("detail", r.text)
        except Exception:
            detail = r.text
        raise RuntimeError(f"{r.status_code}: {detail}")
    return r.json() if r.content else None


def health_ok() -> bool:
    try:
        r = requests.get(f"{API_BASE}/health", timeout=5)
        return r.status_code == 200 and r.json().get("database") == "ok"
    except Exception:
        return False


def esc(s: str) -> str:
    return html.escape(s or "")


# ---------- conversation persistence (backend-backed) -----------------------

def fetch_conversation_list() -> list:
    """GET /conversations -> [{session_id, title, last_message_at, message_count}, ...]
    Returns [] on any failure (e.g. fresh install, no history yet, backend
    down) so the app degrades to an empty sidebar rather than crashing."""
    try:
        return api("GET", "/conversations") or []
    except RuntimeError:
        return []


def fetch_conversation_messages(session_id: str) -> list:
    """GET /conversations/{session_id} -> raw stored turns. Returns [] if
    the session has no server-side history (e.g. it was just created and
    nothing has been asked yet)."""
    try:
        return api("GET", f"/conversations/{session_id}") or []
    except RuntimeError:
        return []


def _hydrate_messages(raw_messages: list) -> list:
    """Convert backend chat_messages rows into the shape the rest of this
    file expects in st.session_state.messages."""
    messages = []
    for m in raw_messages:
        if m["role"] == "user":
            messages.append({"role": "user", "content": m["content"]})
        else:
            meta = m.get("metadata") or {}
            messages.append({
                "role": "assistant",
                "content": m["content"],
                "citations": meta.get("citations") or [],
                "abstained": meta.get("abstained", False),
                "resolved_query": meta.get("resolved_query"),
                "original_question": meta.get("original_question"),
                "query": meta.get("original_question"),
            })
    return messages


# ============================================================================
# SESSION STATE
# ============================================================================

def init_session():
    defaults = {
        "conversations": {},       # keyed by session_id now (was a separate uuid before)
        "current_conv_id": None,
        "session_id": str(uuid.uuid4()),
        "messages": [],
        "api_token": DEFAULT_TOKEN,
        "pipeline": "improved",
        "page": "Chat",
        "feedback_state": {},
        "pending_query": None,
        "remote_history_loaded": False,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

    # One-time hydration per browser session: pull the conversation list
    # from Postgres so refreshing the page doesn't wipe the sidebar.
    if not st.session_state.remote_history_loaded:
        for conv in fetch_conversation_list():
            sid = conv["session_id"]
            st.session_state.conversations[sid] = {
                "title": conv.get("title") or "Conversation",
                "ts": _parse_ts(conv.get("last_message_at")),
                "messages": [],          # lazy-loaded on open, see load_conversation()
                "session_id": sid,
            }
        st.session_state.remote_history_loaded = True


def _parse_ts(value) -> datetime:
    if not value:
        return datetime.now()
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return datetime.now()


def _save_current_conversation():
    cid = st.session_state.current_conv_id
    if cid and cid in st.session_state.conversations:
        st.session_state.conversations[cid]["messages"] = list(st.session_state.messages)


def new_conversation():
    """session_id IS the conversation id now -- one identifier, not two.
    The backend already partitions chat_messages by session_id, so reusing
    it as the sidebar key means a fresh conversation here is automatically
    a fresh row-group in Postgres with nothing extra to track."""
    _save_current_conversation()
    new_sid = str(uuid.uuid4())
    st.session_state.current_conv_id = new_sid
    st.session_state.session_id = new_sid
    st.session_state.messages = []
    st.session_state.feedback_state = {}
    st.session_state.pending_query = None
    st.session_state.conversations[new_sid] = {
        "title": "New conversation",
        "ts": datetime.now(),
        "messages": [],
        "session_id": new_sid,
    }


def load_conversation(cid: str):
    if cid == st.session_state.current_conv_id:
        return
    _save_current_conversation()
    conv = st.session_state.conversations.get(cid)
    if not conv:
        return
    if not conv["messages"]:
        raw = fetch_conversation_messages(cid)
        conv["messages"] = _hydrate_messages(raw)
    st.session_state.current_conv_id = cid
    st.session_state.session_id = conv["session_id"]
    st.session_state.messages = list(conv["messages"])
    st.session_state.feedback_state = {}
    st.session_state.pending_query = None


def delete_conversation(cid: str):
    st.session_state.conversations.pop(cid, None)
    if cid == st.session_state.current_conv_id:
        st.session_state.current_conv_id = None
        st.session_state.messages = []
        st.session_state.session_id = str(uuid.uuid4())


# ============================================================================
# NAV
# ============================================================================

NAV_OPTIONS = ["Chat", "Upload", "Documents", "Settings"]


# ============================================================================
# SIDEBAR
# ============================================================================

def render_sidebar():
    with st.sidebar:
        st.markdown(
            '<div class="side-brand">'
            '<div class="side-brand-name">Knowledge Base</div>'
            '<div class="side-brand-sub">'
            '<span class="side-brand-dot"></span>'
            f'{esc(st.session_state.pipeline)} pipeline'
            '</div>'
            '</div>',
            unsafe_allow_html=True,
        )

        st.markdown('<div class="side-label" style="margin-top:0">Navigate</div>', unsafe_allow_html=True)
        current_idx = NAV_OPTIONS.index(st.session_state.page)
        choice = st.radio(
            "nav",
            NAV_OPTIONS,
            index=current_idx,
            label_visibility="collapsed",
            key="side_nav",
        )
        if choice != st.session_state.page:
            st.session_state.page = choice
            st.rerun()

        if st.button("+  New conversation", use_container_width=True, key="new_conv_btn"):
            new_conversation()
            st.session_state.page = "Chat"
            st.rerun()

        # Conversations with at least one message locally OR known from the
        # backend (message_count > 0 there, message list just not fetched
        # yet). We show every conversation returned by the server, plus any
        # local one that already has messages this session.
        convs = {
            cid: c for cid, c in st.session_state.conversations.items()
            if c["messages"] or cid != st.session_state.current_conv_id or c["title"] != "New conversation"
        }
        if convs:
            sorted_convs = sorted(convs.items(), key=lambda kv: kv[1]["ts"], reverse=True)
            groups = defaultdict(list)
            today = date.today()
            for cid, c in sorted_convs:
                d = c["ts"].date()
                if d == today:
                    key = "Today"
                elif (today - d).days == 1:
                    key = "Yesterday"
                elif (today - d).days < 7:
                    key = d.strftime("%A")
                else:
                    key = d.strftime("%b %d, %Y")
                groups[key].append((cid, c))

            for label, items in groups.items():
                st.markdown(f'<div class="side-label">{esc(label)}</div>', unsafe_allow_html=True)
                for cid, c in items:
                    is_active = cid == st.session_state.current_conv_id
                    if is_active:
                        st.markdown(
                            f'<style>'
                            f'[data-testid="stSidebar"] button[title="conversation:{cid}"],'
                            f'[data-testid="stSidebar"] section button[title="conversation:{cid}"],'
                            f'[data-testid="stSidebar"] [data-testid="stSidebarContent"] button[title="conversation:{cid}"] {{'
                            f'background: #f0ebe0 !important;'
                            f'color: #17181a !important;'
                            f'border-color: #dfe3dc !important;'
                            f'box-shadow: inset 3px 0 0 #b7782d !important;'
                            f'}}'
                            f'</style>',
                            unsafe_allow_html=True,
                        )
                    if st.button(
                        c["title"][:44],
                        key=f"conv_{cid}",
                        help=f"conversation:{cid}",
                        use_container_width=True,
                    ):
                        load_conversation(cid)
                        st.session_state.page = "Chat"
                        st.rerun()


# ============================================================================
# PAGE HEADER
# ============================================================================

def render_page_header(title: str, right_text: str | None = None):
    if right_text:
        c_title, c_right = st.columns([8, 2], gap="small")
        with c_title:
            st.markdown(f'<div class="page-title">{esc(title)}</div>', unsafe_allow_html=True)
        with c_right:
            st.markdown(f'<div class="page-subtitle">{esc(right_text)}</div>', unsafe_allow_html=True)
    else:
        st.markdown(f'<div class="page-title">{esc(title)}</div>', unsafe_allow_html=True)
    st.markdown('<div class="page-rule"></div>', unsafe_allow_html=True)


# ============================================================================
# QUERY PROGRESS
# ============================================================================

STAGES = [
    ("Understanding your question", 3),
    ("Searching documents", 18),
    ("Reranking results", 6),
    ("Generating answer", 15),
]


def _render_progress(stages, current_idx: int, elapsed: float):
    rows = ""
    for i, (label, _) in enumerate(stages):
        if i < current_idx:
            state, icon = "done", "&#10003;"
        elif i == current_idx:
            state, icon = "active", "&#9679;"
        else:
            state, icon = "pending", "&#9675;"
        rows += (
            f'<div class="progress-stage progress-{state}">'
            f'<span class="progress-icon">{icon}</span>'
            f'<span class="progress-label">{esc(label)}</span>'
            f'</div>'
        )
    card = (
        '<div class="progress-card">'
        f'<div class="progress-header"><span>Working</span><span class="progress-time">{elapsed:.0f}s</span></div>'
        f'{rows}'
        '</div>'
    )
    st.markdown(card, unsafe_allow_html=True)


def run_query_with_progress(prompt: str) -> tuple[dict | None, str | None]:
    """IMPORTANT: st.session_state is NOT thread-safe. Everything the
    background thread needs (pipeline, session_id, api_token) is read on
    the main thread first and passed in as arguments."""
    pipeline = st.session_state.pipeline
    session_id = st.session_state.session_id
    token = st.session_state.get("api_token", DEFAULT_TOKEN)

    result: dict = {}

    def _do_query():
        try:
            resp = requests.post(
                f"{API_BASE}/query",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json={"question": prompt, "pipeline": pipeline, "session_id": session_id},
                timeout=300,
            )
            if resp.status_code >= 400:
                try:
                    detail = resp.json().get("detail", resp.text)
                except Exception:
                    detail = resp.text
                result["error"] = f"{resp.status_code}: {detail}"
                return
            result["resp"] = resp.json()
        except Exception as e:
            result["error"] = str(e)

    t = threading.Thread(target=_do_query, daemon=True)
    t.start()

    placeholder = st.empty()
    start = time.time()
    last_idx = -1

    while t.is_alive():
        elapsed = time.time() - start
        cum = 0
        idx = 0
        for i, (_, dur) in enumerate(STAGES):
            cum += dur
            if elapsed < cum:
                idx = i
                break
        else:
            idx = len(STAGES) - 1

        if idx != last_idx:
            last_idx = idx
            with placeholder.container():
                _render_progress(STAGES, idx, elapsed)
        else:
            if int(elapsed) != int(elapsed - 0.5):
                with placeholder.container():
                    _render_progress(STAGES, idx, elapsed)
        time.sleep(0.4)

    placeholder.empty()

    if "error" in result:
        return None, result["error"]
    return result.get("resp"), None


# ============================================================================
# MESSAGES
# ============================================================================

def render_user_message(text: str):
    st.markdown(f'<div class="user-row"><div class="user-bubble">{esc(text)}</div></div>', unsafe_allow_html=True)


def render_sources(citations: list):
    if not citations:
        return
    items = ""
    for i, c in enumerate(citations, 1):
        page = f'<span class="source-meta">p.{c["page_number"]}</span>' if c.get("page_number") else ""
        sect = f'<span class="source-meta">{esc(c["section_title"])}</span>' if c.get("section_title") else ""
        score = f'<span class="source-score">{c["score"]:.3f}</span>'
        items += (
            '<div class="source-item">'
            f'<div class="source-num">{i}</div>'
            '<div class="source-body">'
            f'<div class="source-file">{esc(c["filename"])}{page}{sect}{score}</div>'
            f'<div class="source-excerpt">{esc(c["excerpt"])}</div>'
            '</div>'
            '</div>'
        )
    count = len(citations)
    label = "source" if count == 1 else "sources"
    block = f'<div class="sources-wrap"><div class="sources-head">{count} {label}</div>{items}</div>'
    st.markdown(block, unsafe_allow_html=True)


def render_assistant_actions(msg_idx: int, msg: dict):
    state = st.session_state.feedback_state.get(msg_idx)

    if state == "up":
        st.markdown('<div class="note note-useful">Marked useful</div>', unsafe_allow_html=True)
        return
    if state == "down":
        st.markdown('<div class="note note-notuseful">Marked not useful</div>', unsafe_allow_html=True)
        return

    if state == "pending_down":
        comment = st.text_input(
            "What was wrong? (optional)",
            key=f"comment_{msg_idx}",
            label_visibility="collapsed",
            placeholder="What was wrong? (optional)",
        )
        c1, c2, _ = st.columns([1, 1, 10], gap="small")
        with c1:
            if st.button("Submit", key=f"submit_{msg_idx}"):
                _submit_feedback(msg, False, comment)
                st.session_state.feedback_state[msg_idx] = "down"
                st.rerun()
        with c2:
            if st.button("Cancel", key=f"cancel_{msg_idx}"):
                st.session_state.feedback_state.pop(msg_idx, None)
                st.rerun()
        return

    c1, c2, _ = st.columns([1, 1, 10], gap="small")
    with c1:
        if st.button("Useful", key=f"up_{msg_idx}"):
            _submit_feedback(msg, True, "")
            st.session_state.feedback_state[msg_idx] = "up"
            st.rerun()
    with c2:
        if st.button("Not useful", key=f"down_{msg_idx}"):
            st.session_state.feedback_state[msg_idx] = "pending_down"
            st.rerun()


def _submit_feedback(msg: dict, is_useful: bool, comment: str):
    try:
        api("POST", "/feedback", json={
            "query": msg.get("query", ""),
            "answer": msg["content"],
            "is_useful": is_useful,
            "comment": comment or None,
        })
    except RuntimeError as e:
        st.toast(f"Feedback not saved: {e}")


def render_assistant_message(msg: dict, idx: int):
    st.markdown('<div class="asst-row"><div class="asst-avatar">K</div><div class="asst-body">', unsafe_allow_html=True)

    st.markdown(msg["content"])

    if msg.get("abstained"):
        st.markdown('<div class="note note-abstain">No relevant evidence found in your documents.</div>', unsafe_allow_html=True)

    rq = msg.get("resolved_query")
    if rq and rq != msg.get("original_question"):
        st.markdown(f'<div class="note note-rewrite">Searched as: <em>{esc(rq)}</em></div>', unsafe_allow_html=True)

    render_sources(msg.get("citations") or [])
    render_assistant_actions(idx, msg)

    st.markdown('</div></div>', unsafe_allow_html=True)


# ============================================================================
# CHAT PAGE
# ============================================================================

EXAMPLE_QUESTIONS = [
    "How many days of paid annual leave do employees get?",
    "What is the response count for JAWS in the screen reader table?",
    "What does the chart in the document show?",
    "What is the document management policy ID?",
]


def _render_empty_state():
    hero = (
        '<div class="hero">'
        '<div class="hero-title">What do you want to know?</div>'
        '<div class="hero-sub">Ask about your PDFs, Word docs, or text files. Every answer shows where it came from.</div>'
        '</div>'
    )
    st.markdown(hero, unsafe_allow_html=True)
    st.markdown('<div class="examples-label">Some questions to start with</div>', unsafe_allow_html=True)

    for i in range(0, len(EXAMPLE_QUESTIONS), 2):
        cols = st.columns(2, gap="small")
        for j, col in enumerate(cols):
            if i + j < len(EXAMPLE_QUESTIONS):
                q = EXAMPLE_QUESTIONS[i + j]
                with col:
                    if st.button(q, key=f"example_{i+j}", help=f"example:{q}"):
                        _send_query(q)
                        st.rerun()


def _send_query(prompt: str):
    if not st.session_state.current_conv_id:
        new_conversation()
    cid = st.session_state.current_conv_id
    conv = st.session_state.conversations[cid]
    if conv["title"] == "New conversation":
        conv["title"] = prompt[:60]
        conv["ts"] = datetime.now()
    st.session_state.messages.append({"role": "user", "content": prompt})
    _save_current_conversation()
    st.session_state.pending_query = prompt


def section_chat():
    sid = st.session_state.session_id
    render_page_header("Ask the knowledge base", right_text=f"session {sid[:8]}")

    if not st.session_state.messages and not st.session_state.pending_query:
        _render_empty_state()

    for i, msg in enumerate(st.session_state.messages):
        if msg["role"] == "user":
            render_user_message(msg["content"])
        else:
            render_assistant_message(msg, i)

    if st.session_state.pending_query:
        prompt = st.session_state.pending_query
        st.session_state.pending_query = None

        resp, error = run_query_with_progress(prompt)

        if error:
            st.session_state.messages.append({
                "role": "assistant", "content": f"Query failed: {error}",
                "citations": [], "abstained": False, "query": prompt,
            })
        else:
            st.session_state.messages.append({
                "role": "assistant",
                "content": resp["answer"],
                "citations": resp.get("citations") or [],
                "abstained": resp.get("abstained", False),
                "resolved_query": resp.get("resolved_query"),
                "original_question": prompt,
                "query": prompt,
            })
            # The backend's /query handler is responsible for writing both
            # turns to chat_messages (see backend/app/api/query.py patch).
            # The frontend has no DB access; duplicating the write here
            # would race the server copy.

        _save_current_conversation()
        st.rerun()

    prompt = st.chat_input("Ask a question...")
    if prompt:
        _send_query(prompt)
        st.rerun()

    st.markdown('<div class="chat-disclaimer">The assistant answers only from your uploaded documents.</div>', unsafe_allow_html=True)


# ============================================================================
# UPLOAD PAGE
# ============================================================================

def section_upload():
    render_page_header("Upload a document")
    st.caption("Limit 200MB per file - PDF, DOCX, TXT, MD")

    uploaded = st.file_uploader("Drag and drop file here", type=["pdf", "docx", "txt", "md"], label_visibility="collapsed")

    if uploaded is not None:
        c1, c2 = st.columns(2)
        with c1:
            dept = st.text_input("Department (optional)", value="", key="upload_dept")
        with c2:
            category = st.text_input("Category (optional)", value="", key="upload_category")

        metadata = {}
        if dept:
            metadata["department"] = dept
        if category:
            metadata["category"] = category

        if st.button("Upload and process", type="primary"):
            with st.spinner(f"Uploading {uploaded.name}..."):
                try:
                    files = {"file": (uploaded.name, uploaded.getvalue(), uploaded.type)}
                    data = {"metadata": _json.dumps(metadata)}
                    resp = api("POST", "/documents", files=files, data=data)
                except RuntimeError as e:
                    st.error(f"Upload failed: {e}")
                    resp = None

            if resp:
                doc_id = resp["id"]
                st.info(f"Uploaded. Processing **{uploaded.name}**...")
                progress = st.progress(0.0, text="Parsing and indexing...")
                done = False
                for i in range(90):
                    time.sleep(2)
                    progress.progress(min((i + 1) / 90, 1.0), text=f"Processing... ({i*2}s)")
                    try:
                        doc = api("GET", f"/documents/{doc_id}")
                    except RuntimeError as e:
                        st.error(f"Status check failed: {e}")
                        done = True
                        break
                    if doc["status"] == "ready":
                        progress.empty()
                        st.success(f"Ready: **{uploaded.name}**")
                        done = True
                        break
                    if doc["status"] == "failed":
                        progress.empty()
                        st.error(f"Processing failed: {doc.get('failure_reason') or 'unknown reason'}")
                        done = True
                        break
                if not done:
                    progress.empty()
                    st.warning("Still processing. Check the Documents tab in a moment.")


# ============================================================================
# DOCUMENTS PAGE
# ============================================================================

def _render_doc_card(d: dict):
    status = d["status"].lower()
    status_label = {"ready": "Ready", "processing": "Processing", "uploaded": "Queued", "failed": "Failed"}.get(status, status.capitalize())

    size_kb = d["size_bytes"] / 1024
    size_str = f"{size_kb:.1f} KB" if size_kb < 1024 else f"{size_kb/1024:.1f} MB"

    meta_items = [f'<span class="doc-meta-item">{size_str}</span>']
    if d.get("doc_metadata"):
        for k, v in d["doc_metadata"].items():
            meta_items.append(f'<span class="doc-meta-item">{esc(k)}: {esc(str(v))}</span>')
    created = (d.get("created_at") or "")[:10]
    if created:
        meta_items.append(f'<span class="doc-meta-item">{created}</span>')

    error_html = f'<div class="doc-error">{esc(d["failure_reason"])}</div>' if d.get("failure_reason") else ""

    card = (
        '<div class="doc-card">'
        '<div class="doc-head">'
        f'<div class="doc-name">{esc(d["filename"])}</div>'
        f'<span class="pill pill-{status}"><span class="pill-dot"></span>{status_label}</span>'
        '</div>'
        f'<div class="doc-meta">{"".join(meta_items)}</div>'
        f'{error_html}'
        '</div>'
    )
    st.markdown(card, unsafe_allow_html=True)


def section_documents():
    render_page_header("Documents")

    try:
        docs = api("GET", "/documents")
    except RuntimeError as e:
        st.error(f"Could not load documents: {e}")
        return

    if not docs:
        hero = (
            '<div class="hero">'
            '<div class="hero-title">No documents yet.</div>'
            '<div class="hero-sub">Upload a PDF, DOCX, TXT, or Markdown file from the Upload tab and it will appear here.</div>'
            '</div>'
        )
        st.markdown(hero, unsafe_allow_html=True)
        return

    st.caption(f"{len(docs)} document{'s' if len(docs) != 1 else ''}")
    for d in sorted(docs, key=lambda x: x.get("created_at", ""), reverse=True):
        _render_doc_card(d)


# ============================================================================
# SETTINGS PAGE
# ============================================================================

def section_settings():
    render_page_header("Settings")

    st.markdown('<div class="side-label" style="margin-left:0">Pipeline</div>', unsafe_allow_html=True)
    pipeline = st.radio(
        "Pipeline",
        options=["improved", "baseline"],
        index=0 if st.session_state.pipeline == "improved" else 1,
        captions=[
            "Hybrid retrieval + reranking + multi-query + compression - slower, higher quality.",
            "Vector search only - fast baseline for comparison.",
        ],
        label_visibility="collapsed",
    )
    st.session_state.pipeline = pipeline

    st.markdown('<div class="side-label" style="margin-left:0; margin-top:2rem">Authentication</div>', unsafe_allow_html=True)
    token = st.text_input(
        "API bearer token", value=st.session_state.api_token, type="password",
        label_visibility="collapsed", placeholder="Bearer token",
    )
    if token != st.session_state.api_token:
        st.session_state.api_token = token
        st.rerun()

    st.markdown('<div class="side-label" style="margin-left:0; margin-top:2rem">Backend</div>', unsafe_allow_html=True)
    st.caption(f"`{API_BASE}`")
    if health_ok():
        st.success("Reachable - database ok")
    else:
        st.error("Unreachable or database down")


# ============================================================================
# MAIN
# ============================================================================

def main():
    st.set_page_config(
        page_title="Knowledge Base",
        page_icon=":large_blue_diamond:",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    inject_css()
    init_session()

    render_sidebar()

    page = st.session_state.page
    if page == "Chat":
        section_chat()
    elif page == "Upload":
        section_upload()
    elif page == "Documents":
        section_documents()
    elif page == "Settings":
        section_settings()


if __name__ == "__main__":
    main()