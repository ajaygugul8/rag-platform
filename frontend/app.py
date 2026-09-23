"""
Streamlit frontend for the Modern RAG Platform.

Design: warm graphite theme with an amber "highlighter" accent (ties into
the product's core idea - marking up a passage in a source document).
Sidebar conversation history, avatar-led assistant messages rendered as
full-width annotated excerpts (not chat bubbles - the answer IS the
product), citations styled as margin notes with a left accent bar, a
4-icon bottom toolbar for navigation, and a back button in each page
header.

Pure HTTP client against the FastAPI backend.

NOTE ON HTML RENDERING: every st.markdown() call that emits HTML uses
single-line string concatenation, not indented triple-quoted strings.
Streamlit interprets any line with 4+ leading spaces inside a markdown
string as a code block, which makes HTML render as literal text.

NOTE ON CSS SPECIFICITY: Streamlit wraps buttons inside st.columns() in
[data-testid="stHorizontalBlock"], and its own theme applies !important
to secondary-button styling within that wrapper. Every custom button
override below therefore ALSO uses !important - a non-!important rule
here will silently lose to Streamlit's default and the button will look
unstyled despite this CSS existing. (This bit us once already - the old
back-button rule had no !important and was fully overridden.)
"""

import html
import json as _json
import os
import time
import uuid
from collections import defaultdict
from datetime import datetime, timedelta

import requests
import streamlit as st

API_BASE = os.environ.get("RAG_API_BASE", "http://localhost:8000")
DEFAULT_TOKEN = os.environ.get("RAG_API_TOKEN", "change-me-dev-token")

# ---- design tokens -------------------------------------------------------
# Warm graphite base + amber "highlighter" accent, instead of the generic
# near-black-plus-purple-gradient AI-chatbot default. Amber is used only
# functionally (active nav state, primary buttons, citation accent bar,
# focus rings) - never as decoration.
BG = "#15130f"
BG_RAISED = "#1c1912"
BG_SUNKEN = "#100e0b"
BORDER = "#2b261d"
BORDER_STRONG = "#3d362a"
INK = "#efe9de"
INK_MUTED = "#a89e8c"
INK_FAINT = "#6e6555"
ACCENT = "#e2a33f"
ACCENT_STRONG = "#f0b859"
ACCENT_INK = "#1c1912"
GOOD = "#7ba05b"
GOOD_BG = "#182317"
GOOD_BORDER = "#2a3a24"
BAD = "#c9604a"
BAD_BG = "#241512"
BAD_BORDER = "#3a241e"
WAIT = "#6d92ad"

NAV_ITEMS = [
    ("Chat", "Chat"),
    ("Upload", "Upload"),
    ("Documents", "Documents"),
    ("Settings", "Settings"),
]

# Text glyphs used as button labels. Kept separate from the `help=` value
# so the CSS button[title="..."] selectors (which match `help=`) keep
# working no matter what glyph is shown - only the glyph changed here,
# not the identifier Streamlit/CSS keys off of.
NAV_GLYPHS = {"Chat": "\u25CF", "Upload": "\u2191", "Documents": "\u2261", "Settings": "\u2699"}


CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Fraunces:opsz,wght@9..144,500;9..144,600&display=swap');

:root {{
    --bg: {BG}; --bg-raised: {BG_RAISED}; --bg-sunken: {BG_SUNKEN};
    --border: {BORDER}; --border-strong: {BORDER_STRONG};
    --ink: {INK}; --ink-muted: {INK_MUTED}; --ink-faint: {INK_FAINT};
    --accent: {ACCENT}; --accent-strong: {ACCENT_STRONG}; --accent-ink: {ACCENT_INK};
    --good: {GOOD}; --bad: {BAD}; --wait: {WAIT};
}}

.stApp {{ background: var(--bg); color: var(--ink); font-family: 'Inter', sans-serif; }}
[data-testid="stHeader"] {{ background: transparent; }}
section.main > div {{ padding-top: 0 !important; }}
.block-container {{
    padding-top: 1.25rem !important; padding-bottom: 6.5rem !important; max-width: 100% !important;
}}

/* ---------------- sidebar ---------------- */
[data-testid="stSidebar"] {{
    background: var(--bg-sunken);
    border-right: 1px solid var(--border);
}}
[data-testid="stSidebar"] > div:first-child {{ padding: 1.1rem 1rem !important; }}

.rag-logo {{ padding: 0 0.1rem 1rem 0.1rem; margin: 0 0 0.9rem 0; border-bottom: 1px solid var(--border); }}
.rag-logo-title {{
    font-family: 'Fraunces', serif; font-weight: 600; font-size: 19px;
    color: var(--ink); letter-spacing: 0.2px;
}}
.rag-logo-sub {{
    font-size: 11px; color: var(--ink-faint); margin-top: 4px;
    display: flex; align-items: center; gap: 6px;
}}
.rag-logo-dot {{
    width: 6px; height: 6px; border-radius: 50%; background: var(--accent); display: inline-block;
}}

[data-testid="stSidebar"] .stButton {{ margin: 0 0 1rem 0 !important; }}
[data-testid="stSidebar"] .stButton > button {{
    background: var(--bg-raised) !important;
    border: 1px solid var(--border-strong) !important;
    color: var(--ink) !important;
    border-radius: 9px !important;
    font-size: 13px !important;
    font-weight: 500 !important;
    padding: 0.6rem 0.8rem !important;
    min-height: 0 !important;
    transition: border-color 0.15s ease, background 0.15s ease !important;
    width: 100% !important;
}}
[data-testid="stSidebar"] .stButton > button:hover {{
    background: var(--bg-sunken) !important;
    border-color: var(--accent) !important;
    color: var(--accent-strong) !important;
}}

.hist-group {{
    font-size: 10.5px; color: var(--ink-faint); font-weight: 600; letter-spacing: 0.4px;
    margin: 1.15rem 0 0.4rem 0.3rem;
}}

/* ---------------- page header ---------------- */
.page-header-title {{ font-size: 17px; font-weight: 600; color: var(--ink); padding-top: 6px; }}
.page-header-right {{
    font-size: 12px; color: var(--ink-faint);
    font-family: ui-monospace, "SF Mono", Menlo, monospace;
    padding-top: 10px; text-align: right;
}}
.page-header-rule {{ border-bottom: 1px solid var(--border); margin: 6px 0 1.5rem 0; }}

/* Icon buttons (Back + bottom nav) share one treatment. Every property
   uses !important - see the module docstring for why that's required
   inside a Streamlit horizontal block. */
button[title="Back"], button[title="Chat"], button[title="Upload"],
button[title="Documents"], button[title="Settings"] {{
    background: transparent !important;
    border: 1px solid transparent !important;
    color: var(--ink-muted) !important;
    padding: 0 !important;
    border-radius: 9px !important;
    transition: all 0.15s ease !important;
    display: flex !important;
    align-items: center !important;
    justify-content: center !important;
}}
button[title="Back"] {{
    font-size: 18px !important; min-height: 32px !important; height: 32px !important; width: 32px !important;
}}
button[title="Chat"], button[title="Upload"], button[title="Documents"], button[title="Settings"] {{
    font-size: 16px !important; min-height: 42px !important; height: 42px !important; width: 42px !important;
    border: 1px solid var(--border) !important;
    background: var(--bg-raised) !important;
}}
button[title="Back"]:hover,
button[title="Chat"]:hover, button[title="Upload"]:hover,
button[title="Documents"]:hover, button[title="Settings"]:hover {{
    background: var(--bg-raised) !important;
    border-color: var(--accent) !important;
    color: var(--accent-strong) !important;
}}
button[title="Back"] p,
button[title="Chat"] p, button[title="Upload"] p, button[title="Documents"] p, button[title="Settings"] p {{
    margin: 0 !important; line-height: 1 !important; color: inherit !important;
}}

/* ---------------- messages ---------------- */
/* User turns stay a compact right-aligned bubble - they're short input,
   not the product. Assistant turns are full-width with no bubble at all:
   the answer IS the product, so it gets room to read like an annotated
   excerpt rather than being squeezed into a chat-bubble shape. */
.user-row {{ display: flex; justify-content: flex-end; margin: 1.4rem 0 1.1rem 0; }}
.user-bubble {{
    background: var(--bg-raised); border: 1px solid var(--border);
    padding: 12px 16px; border-radius: 12px 12px 3px 12px;
    max-width: 62%; color: var(--ink); font-size: 14.5px; line-height: 1.5;
}}

.asst-row {{ display: flex; gap: 12px; margin: 0 0 2.1rem 0; align-items: flex-start; }}
.asst-avatar {{
    width: 28px; height: 28px; flex-shrink: 0; margin-top: 3px;
    background: var(--bg-raised); border: 1px solid var(--border-strong);
    border-radius: 7px; display: flex; align-items: center; justify-content: center;
    color: var(--accent); font-weight: 600; font-size: 12px; font-family: 'Fraunces', serif;
}}
.asst-body {{ flex: 1; min-width: 0; padding-top: 3px; }}

[data-testid="stMarkdownContainer"] p {{ color: var(--ink); font-size: 15px; line-height: 1.65; }}
[data-testid="stMarkdownContainer"] strong {{ color: #fff; font-weight: 600; }}
[data-testid="stMarkdownContainer"] a, [data-testid="stMarkdownContainer"] a:visited {{ color: var(--accent-strong); }}
[data-testid="stMarkdownContainer"] code {{
    background: var(--bg-raised); padding: 1px 6px; border-radius: 4px;
    font-size: 13px; color: var(--accent-strong); border: 1px solid var(--border);
}}

/* Citations: a "margin note" treatment - a left accent bar, distinct
   from a generic bordered card, signaling "this is retrieved evidence"
   rather than another app-chrome panel. */
.sources-details {{
    margin-top: 1rem; border: 1px solid var(--border); border-left: 3px solid var(--accent);
    border-radius: 4px 8px 8px 4px; background: var(--bg-raised); overflow: hidden;
}}
.sources-details summary {{
    padding: 0.7rem 0.95rem; cursor: pointer; color: var(--ink-muted); font-size: 12.5px;
    font-weight: 500; list-style: none; display: flex; align-items: center; gap: 8px; user-select: none;
}}
.sources-details summary::-webkit-details-marker {{ display: none; }}
.sources-details summary::after {{
    content: "\\2304"; margin-left: auto; color: var(--ink-faint);
    transition: transform 0.15s ease; font-size: 14px;
}}
.sources-details[open] summary::after {{ transform: rotate(180deg); }}
.source-item {{ padding: 0.75rem 0.95rem; border-top: 1px solid var(--border); }}
.source-meta {{ font-size: 12px; color: var(--ink-muted); margin-bottom: 5px; }}
.source-meta .filename {{ color: var(--ink); font-weight: 500; }}
.source-meta .score {{
    color: var(--ink-faint); font-family: ui-monospace, monospace; font-size: 11px; margin-left: 8px;
}}
.source-excerpt {{ font-size: 12.5px; color: var(--ink-muted); line-height: 1.6; }}

.useful-pill {{
    display: inline-flex; align-items: center; gap: 6px;
    background: var(--good-bg, {GOOD_BG}); border: 1px solid var(--good-border, {GOOD_BORDER}); color: var(--good);
    padding: 4px 12px; border-radius: 999px; font-size: 12px; font-weight: 500; margin-top: 0.9rem;
}}
.useful-pill.down {{ background: {BAD_BG}; border-color: {BAD_BORDER}; color: var(--bad); }}
.abstain-note {{
    display: inline-block; color: var(--accent); font-size: 12.5px; margin-top: 0.7rem;
    padding: 6px 11px; background: rgba(226,163,63,0.08); border: 1px solid rgba(226,163,63,0.25);
    border-radius: 6px;
}}
.rewrite-note {{ color: var(--ink-faint); font-size: 12px; margin-top: 0.55rem; }}
.rewrite-note em {{ color: var(--ink-muted); font-style: normal; }}

/* thumbs-up/down + submit/cancel buttons inside horizontal blocks */
[data-testid="stHorizontalBlock"] button[kind="secondary"] {{
    background: var(--bg-raised) !important; border: 1px solid var(--border) !important;
    color: var(--ink-muted) !important; border-radius: 8px !important;
    padding: 0.4rem 0.9rem !important; font-size: 13px !important;
    min-height: 0 !important; height: auto !important; width: auto !important;
    transition: all 0.15s ease !important;
}}
[data-testid="stHorizontalBlock"] button[kind="secondary"]:hover {{
    background: var(--bg-sunken) !important; border-color: var(--accent) !important; color: var(--accent-strong) !important;
}}
/* Primary buttons (Upload) get the accent treatment - the one place
   amber appears as a solid fill, reserved for the primary action. */
button[kind="primary"] {{
    background: var(--accent) !important; color: var(--accent-ink) !important;
    border: 1px solid var(--accent) !important; border-radius: 8px !important; font-weight: 600 !important;
}}
button[kind="primary"]:hover {{ background: var(--accent-strong) !important; border-color: var(--accent-strong) !important; }}

[data-testid="stChatInput"] {{
    background: var(--bg-raised) !important; border: 1px solid var(--border-strong) !important;
    border-radius: 14px !important; margin-bottom: 0 !important;
}}
[data-testid="stChatInput"]:focus-within {{
    border-color: var(--accent) !important; box-shadow: 0 0 0 3px rgba(226,163,63,0.15) !important;
}}
[data-testid="stChatInput"] textarea {{ color: var(--ink) !important; background: transparent !important; font-size: 14.5px !important; }}
[data-testid="stChatInput"] textarea::placeholder {{ color: var(--ink-faint) !important; }}
[data-testid="stChatInput"] button {{ background: var(--accent) !important; color: var(--accent-ink) !important; border: none !important; border-radius: 50% !important; }}

.page-h2 {{ font-family: 'Fraunces', serif; font-size: 22px; font-weight: 600; color: var(--ink); margin-bottom: 1.3rem; }}

.empty-state {{ text-align: center; padding: 4.5rem 0 3rem 0; }}
.empty-state-title {{
    font-family: 'Fraunces', serif; font-size: 20px; font-weight: 500; color: var(--ink-muted); margin-bottom: 0.5rem;
}}
.empty-state-sub {{ font-size: 13px; color: var(--ink-faint); }}

/* ---------------- conversation history buttons ---------------- */
[data-testid="stSidebar"] button[title^="conversation:"] {{
    background: transparent !important;
    border: 1px solid transparent !important;
    color: #b8b8c8 !important;
    font-size: 12.5px !important;
    font-weight: 400 !important;
    text-align: left !important;
    justify-content: flex-start !important;
    padding: 0.45rem 0.55rem !important;
    border-radius: 6px !important;
    min-height: 0 !important;
    height: auto !important;
    width: 100% !important;
    margin: 0 0 1px 0 !important;
    transition: background 0.12s ease, color 0.12s ease !important;
    overflow: hidden !important;
}}
[data-testid="stSidebar"] button[title^="conversation:"]:hover {{
    background: #1a1a26 !important;
    border-color: transparent !important;
    color: #e4e4ec !important;
}}
[data-testid="stSidebar"] button[title^="conversation:"] p {{
    font-size: 12.5px !important;
    margin: 0 !important;
    text-align: left !important;
    overflow: hidden !important;
    text-overflow: ellipsis !important;
    white-space: nowrap !important;
    width: 100% !important;
    color: inherit !important;
}}
[data-testid="stSidebar"] button[title^="conversation:"] > div {{
    text-align: left !important;
    justify-content: flex-start !important;
    width: 100% !important;
}}

/* document status badges */
.status-badge {{
    display: inline-flex; align-items: center; gap: 6px; font-size: 11.5px; font-weight: 500;
    padding: 3px 10px; border-radius: 999px; text-transform: capitalize;
}}
.status-dot {{ width: 6px; height: 6px; border-radius: 50%; }}
.status-ready {{ background: {GOOD_BG}; color: var(--good); border: 1px solid {GOOD_BORDER}; }}
.status-ready .status-dot {{ background: var(--good); }}
.status-processing {{ background: rgba(109,146,173,0.1); color: var(--wait); border: 1px solid rgba(109,146,173,0.25); }}
.status-processing .status-dot {{ background: var(--wait); }}
.status-uploaded {{ background: var(--bg-raised); color: var(--ink-muted); border: 1px solid var(--border-strong); }}
.status-uploaded .status-dot {{ background: var(--ink-faint); }}
.status-failed {{ background: {BAD_BG}; color: var(--bad); border: 1px solid {BAD_BORDER}; }}
.status-failed .status-dot {{ background: var(--bad); }}

::-webkit-scrollbar {{ width: 8px; height: 8px; }}
::-webkit-scrollbar-track {{ background: transparent; }}
::-webkit-scrollbar-thumb {{ background: var(--border-strong); border-radius: 4px; }}
::-webkit-scrollbar-thumb:hover {{ background: var(--ink-faint); }}
</style>
"""


# ------------------------------------------------------------------ helpers

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


def init_session():
    # In-browser-only conversation state. Refreshing the page intentionally
    # clears saved history because this UI does not persist to a backend.
    defaults = {
        "conversations": {},
        "current_conv_id": None,
        "session_id": str(uuid.uuid4()),
        "messages": [],
        "api_token": DEFAULT_TOKEN,
        "pipeline": "improved",
        "page": "Chat",
        "page_history": [],
        "feedback_state": {},
        "pending_query": None,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


def _save_current_conversation():
    """Persist the in-memory messages back to the conversations dict."""
    cid = st.session_state.current_conv_id
    if cid and cid in st.session_state.conversations:
        st.session_state.conversations[cid]["messages"] = list(st.session_state.messages)


def new_conversation():
    """Save the current conversation, then start a fresh empty one."""
    _save_current_conversation()
    new_id = str(uuid.uuid4())
    st.session_state.current_conv_id = new_id
    st.session_state.session_id = str(uuid.uuid4())
    st.session_state.messages = []
    st.session_state.feedback_state = {}
    st.session_state.pending_query = None
    st.session_state.conversations[new_id] = {
        "title": "New conversation",
        "ts": datetime.now(),
        "messages": [],
        "session_id": st.session_state.session_id,
    }


def load_conversation(cid: str):
    """Switch to a previously saved conversation."""
    if cid == st.session_state.current_conv_id:
        return
    _save_current_conversation()
    conv = st.session_state.conversations.get(cid)
    if not conv:
        return
    st.session_state.current_conv_id = cid
    st.session_state.session_id = conv["session_id"]
    st.session_state.messages = list(conv["messages"])
    st.session_state.feedback_state = {}
    st.session_state.pending_query = None


def esc(s: str) -> str:
    return html.escape(s or "")


# ------------------------------------------------------------------ navigation

def navigate_to(page: str):
    """Switch page, remembering where we came from so Back can return."""
    if st.session_state.page == page:
        return
    st.session_state.page_history.append(st.session_state.page)
    st.session_state.page = page


def go_back():
    """Return to the previous page, if any."""
    if st.session_state.page_history:
        st.session_state.page = st.session_state.page_history.pop()


# ------------------------------------------------------------------ nav toolbar

def render_nav_icons():
    """Four-icon navigation toolbar with native browser tooltips."""
    active = st.session_state.page

    # Highlight the button whose title matches the active page.
    st.markdown(
        f'<style>'
        f'button[title="{active}"]{{'
        f'background:var(--accent)!important;'
        f'color:var(--accent-ink)!important;border-color:var(--accent)!important;'
        f'}}'
        f'</style>',
        unsafe_allow_html=True,
    )

    cols = st.columns([1, 1, 1, 1, 8], gap="small")
    for col, (name, _title) in zip(cols, NAV_ITEMS):
        with col:
            if st.button(NAV_GLYPHS[name], key=f"nav_icon_{name}", help=name):
                if st.session_state.page != name:
                    navigate_to(name)
                    st.rerun()


# ------------------------------------------------------------------ page header

def render_page_header(title: str, right_text: str | None = None):
    """Page header: optional back button, title, optional right-side text."""
    has_back = bool(st.session_state.page_history)

    if right_text is not None:
        c_back, c_title, c_right = st.columns([0.5, 15, 3], gap="small")
    else:
        c_back, c_title = st.columns([0.5, 15], gap="small")
        c_right = None

    with c_back:
        if has_back:
            if st.button("\u2190", key=f"back_{title}", help="Back"):
                go_back()
                st.rerun()

    with c_title:
        st.markdown(
            f'<div class="page-header-title">{esc(title)}</div>',
            unsafe_allow_html=True,
        )

    if c_right is not None:
        with c_right:
            st.markdown(
                f'<div class="page-header-right">{esc(right_text)}</div>',
                unsafe_allow_html=True,
            )

    st.markdown('<div class="page-header-rule"></div>', unsafe_allow_html=True)


# ------------------------------------------------------------------ sidebar

def render_sidebar():
    with st.sidebar:
        logo_html = (
            '<div class="rag-logo">'
            '<div class="rag-logo-title">Knowledge Base</div>'
            '<div class="rag-logo-sub">'
            '<span class="rag-logo-dot"></span>'
            f'{esc(st.session_state.pipeline.capitalize())} pipeline'
            '</div>'
            '</div>'
        )
        st.markdown(logo_html, unsafe_allow_html=True)

        if st.button("New conversation", use_container_width=True, key="new_conv_btn"):
            new_conversation()
            if st.session_state.page != "Chat":
                navigate_to("Chat")
            st.rerun()

        convs = {
            cid: c for cid, c in st.session_state.conversations.items() if c["messages"]
        }
        if convs:
            sorted_convs = sorted(convs.items(), key=lambda kv: kv[1]["ts"], reverse=True)
            groups = defaultdict(list)
            today = datetime.now().date()
            for cid, c in sorted_convs:
                d = c["ts"].date()
                key = "Today" if d == today else d.strftime("%b %d")
                groups[key].append((cid, c))

            for label, items in groups.items():
                st.markdown(
                    f'<div class="hist-group">{esc(label)}</div>',
                    unsafe_allow_html=True,
                )
                for cid, c in items:
                    is_active = cid == st.session_state.current_conv_id
                    if is_active:
                        st.markdown(
                            f'<style>'
                            f'button[title="conversation:{cid}"]{{'
                            f'background:#1a1a26!important;color:#e4e4ec!important;'
                            f'border-color:#2a2a3a!important;'
                            f'}}'
                            f'</style>',
                            unsafe_allow_html=True,
                        )
                    if st.button(
                        c["title"][:38],
                        key=f"conv_{cid}",
                        help=f"conversation:{cid}",
                        use_container_width=True,
                    ):
                        load_conversation(cid)
                        if st.session_state.page != "Chat":
                            navigate_to("Chat")
                        st.rerun()


# ------------------------------------------------------------------ sources

def render_sources(citations):
    if not citations:
        return

    items_html = ""
    for c in citations:
        page = f" &middot; p.{c['page_number']}" if c.get("page_number") else ""
        sect = f" &middot; {esc(c['section_title'])}" if c.get("section_title") else ""
        items_html += (
            '<div class="source-item">'
            '<div class="source-meta">'
            f'<span class="filename">{esc(c["filename"])}</span>{page}{sect}'
            f'<span class="score">{c["score"]:.3f}</span>'
            '</div>'
            f'<div class="source-excerpt">{esc(c["excerpt"])}</div>'
            '</div>'
        )

    count = len(citations)
    label = "source" if count == 1 else "sources"
    block = (
        '<details class="sources-details">'
        f'<summary>{count} {label}</summary>'
        + items_html
        + '</details>'
    )
    st.markdown(block, unsafe_allow_html=True)


# ------------------------------------------------------------------ feedback

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


def render_feedback(msg_idx: int, msg: dict):
    state = st.session_state.feedback_state.get(msg_idx)

    if state == "up":
        st.markdown('<div class="useful-pill">Marked useful</div>', unsafe_allow_html=True)
        return

    if state == "down":
        st.markdown('<div class="useful-pill down">Marked not useful</div>', unsafe_allow_html=True)
        return

    if state == "pending_down":
        comment = st.text_input(
            "What was wrong? (optional)", key=f"comment_{msg_idx}",
            label_visibility="collapsed", placeholder="What was wrong? (optional)",
        )
        c1, c2, _ = st.columns([1, 1, 8], gap="small")
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
        if st.button("Useful", key=f"up_{msg_idx}", help="Mark useful"):
            _submit_feedback(msg, True, "")
            st.session_state.feedback_state[msg_idx] = "up"
            st.rerun()
    with c2:
        if st.button("Not useful", key=f"down_{msg_idx}", help="Mark not useful"):
            st.session_state.feedback_state[msg_idx] = "pending_down"
            st.rerun()


# ------------------------------------------------------------------ messages

def render_user_message(text: str):
    st.markdown(
        f'<div class="user-row"><div class="user-bubble">{esc(text)}</div></div>',
        unsafe_allow_html=True,
    )


def render_assistant_message(msg: dict, idx: int):
    st.markdown('<div class="asst-row"><div class="asst-avatar">K</div><div class="asst-body">', unsafe_allow_html=True)

    st.markdown(msg["content"])

    if msg.get("abstained"):
        st.markdown(
            '<div class="abstain-note">No relevant evidence found in the knowledge base.</div>',
            unsafe_allow_html=True,
        )

    rq = msg.get("resolved_query")
    if rq and rq != msg.get("original_question"):
        st.markdown(
            f'<div class="rewrite-note">Searched as: <em>{esc(rq)}</em></div>',
            unsafe_allow_html=True,
        )

    render_sources(msg.get("citations") or [])
    render_feedback(idx, msg)

    st.markdown('</div></div>', unsafe_allow_html=True)


# ------------------------------------------------------------------ chat

def section_chat():
    sid = st.session_state.session_id
    render_page_header("Ask the knowledge base", right_text=f"Session {sid[:8]}")

    if not st.session_state.messages and not st.session_state.pending_query:
        empty_html = (
            '<div class="empty-state">'
            '<div class="empty-state-title">Ask anything about your documents</div>'
            '<div class="empty-state-sub">Your questions and sources will appear here.</div>'
            '</div>'
        )
        st.markdown(empty_html, unsafe_allow_html=True)

    for i, msg in enumerate(st.session_state.messages):
        if msg["role"] == "user":
            render_user_message(msg["content"])
        else:
            render_assistant_message(msg, i)

    if st.session_state.pending_query:
        prompt = st.session_state.pending_query
        with st.spinner("Searching your documents...(It will take a minute)"):
            try:
                resp = api("POST", "/query", json={
                    "question": prompt,
                    "pipeline": st.session_state.pipeline,
                    "session_id": st.session_state.session_id,
                })
                st.session_state.messages.append({
                    "role": "assistant",
                    "content": resp["answer"],
                    "citations": resp.get("citations") or [],
                    "abstained": resp.get("abstained", False),
                    "resolved_query": resp.get("resolved_query"),
                    "original_question": prompt,
                    "query": prompt,
                })
            except RuntimeError as e:
                st.session_state.messages.append({
                    "role": "assistant",
                    "content": f"Query failed: {e}",
                    "citations": [],
                    "abstained": False,
                    "query": prompt,
                })
        _save_current_conversation()
        st.session_state.pending_query = None
        st.rerun()

    render_nav_icons()

    prompt = st.chat_input("Ask a question about your documents...")
    if prompt:
        # Ensure a conversation exists
        if not st.session_state.current_conv_id:
            new_conversation()
        cid = st.session_state.current_conv_id
        conv = st.session_state.conversations[cid]

        # First message becomes the title
        if conv["title"] == "New conversation":
            conv["title"] = prompt[:40]
            conv["ts"] = datetime.now()  # bump to top of the sidebar

        st.session_state.messages.append({"role": "user", "content": prompt})
        _save_current_conversation()
        st.session_state.pending_query = prompt
        st.rerun()


# ------------------------------------------------------------------ upload

def section_upload():
    render_page_header("Upload a document")
    st.caption("PDF, DOCX, TXT, or Markdown \u00b7 max 25 MB")

    uploaded = st.file_uploader(
        "Choose a file", type=["pdf", "docx", "txt", "md"],
        label_visibility="collapsed",
    )

    if uploaded is not None:
        col1, col2 = st.columns(2)
        with col1:
            dept = st.text_input("Department (optional)", value="")
        with col2:
            category = st.text_input("Category (optional)", value="")

        metadata = {}
        if dept:
            metadata["department"] = dept
        if category:
            metadata["category"] = category

        if st.button("Upload", type="primary"):
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
                st.info(f"Uploaded. Processing {uploaded.name}...")
                progress = st.progress(0.0)
                done = False
                for i in range(60):
                    time.sleep(2)
                    progress.progress(min((i + 1) / 60, 1.0))
                    try:
                        doc = api("GET", f"/documents/{doc_id}")
                    except RuntimeError as e:
                        st.error(f"Status check failed: {e}")
                        done = True
                        break
                    if doc["status"] == "ready":
                        progress.empty()
                        st.success(f"Ready: **{uploaded.name}** \u2014 you can now ask questions about it.")
                        done = True
                        break
                    if doc["status"] == "failed":
                        progress.empty()
                        st.error(f"Processing failed: {doc.get('failure_reason') or 'unknown reason'}")
                        done = True
                        break
                if not done:
                    progress.empty()
                    st.warning("Still processing. Check the Documents tab shortly.")

    render_nav_icons()


# ------------------------------------------------------------------ documents

def section_documents():
    render_page_header("Documents in the knowledge base")

    try:
        docs = api("GET", "/documents")
    except RuntimeError as e:
        st.error(f"Could not load documents: {e}")
        render_nav_icons()
        return

    if not docs:
        empty_html = (
            '<div class="empty-state">'
            '<div class="empty-state-title">No documents yet</div>'
            '<div class="empty-state-sub">Upload one from the Upload tab to get started.</div>'
            '</div>'
        )
        st.markdown(empty_html, unsafe_allow_html=True)
        render_nav_icons()
        return

    st.caption(f"{len(docs)} document{'s' if len(docs) != 1 else ''}")
    for d in sorted(docs, key=lambda x: x.get("created_at", ""), reverse=True):
        status_key = d["status"].lower()
        cols = st.columns([6, 2, 2])
        with cols[0]:
            st.markdown(f"**{esc(d['filename'])}**")
            if d.get("doc_metadata"):
                st.caption(", ".join(f"{k}: {v}" for k, v in d["doc_metadata"].items()))
        with cols[1]:
            st.caption(f"{d['size_bytes']:,} bytes")
        with cols[2]:
            st.markdown(
                f'<span class="status-badge status-{status_key}">'
                f'<span class="status-dot"></span>{esc(d["status"])}</span>',
                unsafe_allow_html=True,
            )
        if d.get("failure_reason"):
            st.caption(f"Error: {d['failure_reason']}")
        st.divider()

    render_nav_icons()


# ------------------------------------------------------------------ settings

def section_settings():
    render_page_header("Settings")

    token = st.text_input("API bearer token", value=st.session_state.api_token, type="password")
    if token != st.session_state.api_token:
        st.session_state.api_token = token
        st.rerun()

    pipeline = st.radio(
        "Pipeline",
        options=["improved", "baseline"],
        index=0 if st.session_state.pipeline == "improved" else 1,
        captions=[
            "Hybrid retrieval + reranking + multi-query + compression (slower, higher quality)",
            "Vector search only (fast baseline for comparison)",
        ],
    )
    st.session_state.pipeline = pipeline

    st.divider()
    st.caption(f"Backend: `{API_BASE}`")
    if health_ok():
        st.success("Backend reachable, database ok")
    else:
        st.error("Backend unreachable or database down")

    render_nav_icons()


# ------------------------------------------------------------------ main

def main():
    st.set_page_config(
        page_title="RAG Platform",
        page_icon="\u25CF",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    st.markdown(CSS, unsafe_allow_html=True)
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