"""
Modern RAG Platform — Streamlit frontend.

Design principles:
  1. The answer is the product. Reading experience comes first.
  2. Progress is visible. RAG takes 30-60s; the user sees what's happening.
  3. Citations are first-class. Numbered margin notes, not a buried expander.
  4. Empty states guide the user with one-click examples, not silence.
  5. Navigation stays out of the way of the primary task.

Pure HTTP client against the FastAPI backend. No app.* imports.

HTML rendering note: every st.markdown() call that emits HTML uses
single-line string concatenation, never indented triple-quoted strings.
Streamlit treats 4+ leading spaces inside a markdown string as a code
block, which renders raw HTML as literal text.

CSS specificity note: Streamlit applies !important to its own button
styling inside [data-testid="stHorizontalBlock"], so every custom button
override here ALSO uses !important. Without it, the rule silently loses.
"""

import html
import json as _json
import os
import threading
import time
import uuid
from collections import defaultdict
from datetime import datetime, date

import requests
import streamlit as st

API_BASE = os.environ.get("RAG_API_BASE", "http://localhost:8000")
DEFAULT_TOKEN = os.environ.get("RAG_API_TOKEN", "change-me-dev-token")

# ---------- design tokens ---------------------------------------------------
BG          = "#ffffff"
BG_RAISED   = "#f9f9f7"
BG_HOVER    = "#f1f4f0"
BORDER      = "#eceae4"
BORDER_HI   = "#dfe3dc"
INK         = "#17181a"
INK_MUTED   = "#2f3740"
INK_FAINT   = "#5d6670"
ACCENT      = "#b7782d"
ACCENT_HI   = "#a26620"
ACCENT_INK  = "#ffffff"
GOOD        = "#2d6d4b"
GOOD_BG     = "#f0f9f4"
GOOD_BORDER = "#d9ebdf"
BAD         = "#b0483d"
BAD_BG      = "#fff4f2"
BAD_BORDER  = "#f1d7d3"
WAIT        = "#4a6ea8"


# ============================================================================
# CSS
# ============================================================================

CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Neuton:wght@400;500;600;700&family=Inter:wght@400;500;600;700&display=swap');

.stApp {{ background: {BG}; color: {INK}; font-family: 'Neuton', 'Inter', -apple-system, sans-serif; }}
.stApp p, .stApp li, .stApp label, .stApp span, .stApp div, .stApp h1, .stApp h2, .stApp h3, .stApp h4, .stApp h5, .stApp h6 {{ color: inherit; }}
[data-testid="stHeader"] {{ background: transparent; height: 0; }}
section.main > div {{ padding-top: 0 !important; }}
.block-container {{ padding: 1.25rem 2.5rem 7rem 2.5rem !important; max-width: 100% !important; }}

[data-testid="stSidebar"] *,
[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p,
[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] div,
[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] span {{ color: {INK} !important; }}

/* ---------- SIDEBAR ---------- */
[data-testid="stSidebar"] {{
    background: {BG_RAISED};
    border-right: 1px solid {BORDER};
    width: 300px !important;
}}

[data-testid="stSidebar"] .stButton > button,
button[title^="conversation:"] {{
    box-shadow: none !important;
}}
[data-testid="stSidebar"] > div:first-child {{ padding: 1.5rem 1.1rem !important; }}
[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p {{ margin: 0 !important; }}

.side-brand {{ padding: 0 0.2rem 1.1rem 0.2rem; border-bottom: 1px solid {BORDER}; margin-bottom: 1.1rem; }}
.side-brand-name {{
    font-family: 'Fraunces', serif; font-weight: 600; font-size: 20px;
    color: {INK}; letter-spacing: -0.2px;
}}
.side-brand-sub {{
    font-size: 11px; color: {INK_FAINT}; margin-top: 5px;
    display: flex; align-items: center; gap: 6px; text-transform: uppercase;
    letter-spacing: 0.6px; font-weight: 500;
}}
.side-brand-dot {{
    width: 6px; height: 6px; border-radius: 50%;
    background: {ACCENT}; box-shadow: 0 0 8px {ACCENT}99;
}}

/* Primary sidebar action (New conversation) */
[data-testid="stSidebar"] .stButton > button {{
    background: {BG} !important;
    border: 1px solid {BORDER_HI} !important;
    color: {INK} !important;
    border-radius: 8px !important;
    font-size: 13.5px !important;
    font-weight: 500 !important;
    padding: 0.6rem 0.85rem !important;
    min-height: 0 !important;
    width: 100% !important;
    transition: all 0.12s ease !important;
}}
[data-testid="stSidebar"] .stButton > button:hover {{
    background: {BG_HOVER} !important;
    border-color: {ACCENT} !important;
    color: {ACCENT_HI} !important;
}}

.side-label {{
    font-size: 10.5px; color: {INK_FAINT}; font-weight: 700;
    text-transform: uppercase; letter-spacing: 1.1px;
    margin: 1.4rem 0 0.7rem 0.3rem;
}}

[data-testid="stSidebar"] .stRadio {{
    margin-top: 0.25rem;
}}
[data-testid="stSidebar"] .stRadio > div {{
    gap: 0.35rem !important;
}}
[data-testid="stSidebar"] .stRadio label {{
    color: {INK_MUTED} !important;
    font-size: 14px !important;
    font-weight: 500 !important;
    border-radius: 8px !important;
    padding: 0.38rem 0.55rem 0.38rem 0.45rem !important;
    transition: all 0.12s ease !important;
}}
[data-testid="stSidebar"] .stRadio label:hover {{
    background: {BG_HOVER} !important;
    color: {INK} !important;
}}
[data-testid="stSidebar"] .stRadio input[type="radio"] {{
    accent-color: {ACCENT} !important;
}}
[data-testid="stSidebar"] .stRadio [data-testid="stMarkdownContainer"] p {{
    color: inherit !important;
    margin: 0 !important;
}}

/* Conversation list items */
[data-testid="stSidebar"] button[title^="conversation:"] {{
    background: transparent !important;
    border: 1px solid transparent !important;
    color: {INK_MUTED} !important;
    font-size: 13px !important;
    font-weight: 400 !important;
    text-align: left !important;
    justify-content: flex-start !important;
    padding: 0.5rem 0.6rem !important;
    border-radius: 6px !important;
    min-height: 0 !important;
    height: auto !important;
    width: 100% !important;
    margin: 0 0 1px 0 !important;
    transition: all 0.1s ease !important;
    overflow: hidden !important;
}}
[data-testid="stSidebar"] button[title^="conversation:"]:hover {{
    background: {BG} !important;
    color: {INK} !important;
}}
[data-testid="stSidebar"] button[title^="conversation:"] p {{
    font-size: 13px !important;
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

/* ---------- MAIN HEADER ---------- */
.page-title {{
    font-family: 'Fraunces', serif; font-size: 24px; font-weight: 600;
    color: {INK}; letter-spacing: -0.3px; padding-top: 4px;
}}
.page-subtitle {{
    font-size: 12.5px; color: {INK_FAINT}; padding-top: 8px;
    text-align: right; font-family: ui-monospace, monospace;
}}
.page-rule {{ border-bottom: 1px solid {BORDER}; margin: 14px 0 1.75rem 0; }}

/* ---------- EMPTY STATE ---------- */
.hero {{ padding: 3rem 0 2.5rem 0; max-width: 640px; }}
.hero-title {{
    font-family: 'Fraunces', serif; font-size: 36px; font-weight: 500;
    color: {INK}; line-height: 1.15; letter-spacing: -0.6px;
    margin-bottom: 0.9rem;
}}
.hero-title em {{ color: {ACCENT}; font-style: italic; }}
.hero-sub {{ font-size: 15px; color: {INK_MUTED}; line-height: 1.6; max-width: 480px; }}

.examples-label {{
    font-size: 11px; color: {INK_FAINT}; text-transform: uppercase;
    letter-spacing: 0.9px; font-weight: 600; margin: 2.5rem 0 0.9rem 0;
}}

/* Example question chips (rendered as buttons via st.columns) */
button[title^="example:"] {{
    background: {BG_RAISED} !important;
    border: 1px solid {BORDER} !important;
    color: {INK_MUTED} !important;
    border-radius: 10px !important;
    font-size: 13px !important;
    font-weight: 400 !important;
    padding: 0.85rem 1.1rem !important;
    min-height: 0 !important;
    height: auto !important;
    width: 100% !important;
    text-align: left !important;
    justify-content: flex-start !important;
    transition: all 0.12s ease !important;
    line-height: 1.4 !important;
}}
button[title^="example:"]:hover {{
    background: {BG_HOVER} !important;
    border-color: {ACCENT} !important;
    color: {INK} !important;
}}
button[title^="example:"] p {{
    margin: 0 !important;
    text-align: left !important;
    font-size: 13px !important;
    color: inherit !important;
}}
button[title^="example:"] > div {{
    text-align: left !important;
    justify-content: flex-start !important;
    width: 100% !important;
}}

/* ---------- MESSAGES ---------- */
.user-row {{ display: flex; justify-content: flex-end; margin: 2rem 0 1.25rem 0; }}
.user-bubble {{
    background: {BG_RAISED}; border: 1px solid {BORDER};
    padding: 12px 18px; border-radius: 14px 14px 4px 14px;
    max-width: 68%; color: {INK}; font-size: 15px; line-height: 1.55;
}}

.asst-row {{ display: flex; gap: 16px; margin: 0 0 2.5rem 0; align-items: flex-start; }}
.asst-avatar {{
    width: 32px; height: 32px; flex-shrink: 0; margin-top: 2px;
    background: linear-gradient(135deg, {BG_RAISED}, {BG} );
    border: 1px solid {BORDER_HI};
    border-radius: 9px;
    display: flex; align-items: center; justify-content: center;
    color: {ACCENT}; font-weight: 600; font-size: 14px;
    font-family: 'Fraunces', serif;
}}
.asst-body {{ flex: 1; min-width: 0; }}
.asst-body [data-testid="stMarkdownContainer"] p {{
    color: {INK}; font-size: 15.5px; line-height: 1.7; margin-bottom: 0.9em;
}}
.asst-body [data-testid="stMarkdownContainer"] strong {{ color: #fff; font-weight: 600; }}
.asst-body [data-testid="stMarkdownContainer"] code {{
    background: {BG_RAISED}; padding: 2px 7px; border-radius: 4px;
    font-size: 13px; color: {ACCENT_HI}; border: 1px solid {BORDER};
}}
.asst-body [data-testid="stMarkdownContainer"] ul, 
.asst-body [data-testid="stMarkdownContainer"] ol {{
    margin-top: 0.4em; margin-bottom: 0.9em;
}}
.asst-body [data-testid="stMarkdownContainer"] li {{
    color: {INK}; font-size: 15.5px; line-height: 1.7; margin-bottom: 0.4em;
}}
.asst-body [data-testid="stMarkdownContainer"] a {{
    color: {ACCENT_HI}; text-decoration: none; border-bottom: 1px solid {ACCENT}55;
}}

/* ---------- CITATIONS (margin notes) ---------- */
.sources-wrap {{ margin-top: 1.4rem; }}
.sources-head {{
    display: flex; align-items: center; gap: 10px;
    padding: 0.7rem 0 0.6rem 0;
    border-bottom: 1px solid {BORDER};
    font-size: 11.5px; color: {INK_FAINT}; font-weight: 600;
    text-transform: uppercase; letter-spacing: 0.9px;
}}
.source-item {{
    display: flex; gap: 14px;
    padding: 0.95rem 0;
    border-bottom: 1px solid {BORDER};
}}
.source-num {{
    flex-shrink: 0; width: 24px; height: 24px;
    background: {BG_RAISED}; border: 1px solid {BORDER_HI};
    border-radius: 6px; display: flex; align-items: center; justify-content: center;
    font-size: 11px; font-weight: 600; color: {ACCENT};
    font-family: ui-monospace, monospace;
}}
.source-body {{ flex: 1; min-width: 0; }}
.source-file {{
    font-size: 13px; color: {INK}; font-weight: 500;
    margin-bottom: 4px;
}}
.source-file .source-meta {{
    color: {INK_FAINT}; font-weight: 400; margin-left: 8px;
}}
.source-file .source-score {{
    color: {INK_FAINT}; font-family: ui-monospace, monospace;
    font-size: 11px; margin-left: 8px;
}}
.source-excerpt {{
    font-size: 13px; color: {INK_MUTED}; line-height: 1.6;
    display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical;
    overflow: hidden;
}}

/* ---------- STATUS NOTES ---------- */
.note {{
    display: inline-flex; align-items: center; gap: 8px;
    padding: 6px 12px; border-radius: 6px;
    font-size: 12.5px; font-weight: 500; margin-top: 0.9rem;
}}
.note-abstain {{
    background: {ACCENT}10; border: 1px solid {ACCENT}44; color: {ACCENT_HI};
}}
.note-rewrite {{
    background: transparent; border: none; color: {INK_FAINT};
    font-size: 12px; font-weight: 400; padding: 4px 0;
}}
.note-rewrite em {{ color: {INK_MUTED}; font-style: normal; }}
.note-useful {{
    background: {GOOD_BG}; border: 1px solid {GOOD_BORDER}; color: {GOOD};
}}
.note-notuseful {{
    background: {BAD_BG}; border: 1px solid {BAD_BORDER}; color: {BAD};
}}

/* ---------- MESSAGE ACTIONS ---------- */
[data-testid="stHorizontalBlock"] button[kind="secondary"] {{
    background: transparent !important;
    border: 1px solid {BORDER} !important;
    color: {INK_MUTED} !important;
    border-radius: 6px !important;
    padding: 0.35rem 0.9rem !important;
    font-size: 12px !important;
    font-weight: 500 !important;
    min-height: 0 !important;
    height: auto !important;
    width: auto !important;
    transition: all 0.12s ease !important;
}}
[data-testid="stHorizontalBlock"] button[kind="secondary"]:hover {{
    background: {BG_RAISED} !important;
    border-color: {BORDER_HI} !important;
    color: {INK} !important;
}}

button[kind="primary"] {{
    background: {ACCENT} !important;
    color: {ACCENT_INK} !important;
    border: 1px solid {ACCENT} !important;
    border-radius: 8px !important;
    font-weight: 600 !important;
    font-size: 14px !important;
    padding: 0.6rem 1.5rem !important;
}}
button[kind="primary"]:hover {{
    background: {ACCENT_HI} !important;
    border-color: {ACCENT_HI} !important;
}}

/* ---------- PROGRESS CARD ---------- */
.progress-card {{
    background: {BG_RAISED};
    border: 1px solid {BORDER};
    border-radius: 12px;
    padding: 1.25rem 1.5rem;
    margin: 1.5rem 0;
    max-width: 480px;
}}
.progress-header {{
    font-size: 12px; color: {INK_FAINT}; font-weight: 500;
    text-transform: uppercase; letter-spacing: 0.9px;
    margin-bottom: 1rem;
    display: flex; justify-content: space-between; align-items: center;
}}
.progress-time {{ font-family: ui-monospace, monospace; color: {INK_MUTED}; }}
.progress-stage {{
    display: flex; align-items: center; gap: 12px;
    padding: 0.45rem 0;
    font-size: 14px;
    color: {INK_FAINT};
}}
.progress-stage.progress-active {{ color: {INK}; }}
.progress-stage.progress-done {{ color: {INK_MUTED}; }}
.progress-icon {{
    flex-shrink: 0; width: 20px; height: 20px;
    display: flex; align-items: center; justify-content: center;
    font-size: 12px;
}}
.progress-stage.progress-pending .progress-icon {{ color: {INK_FAINT}; }}
.progress-stage.progress-active .progress-icon {{
    color: {ACCENT};
    animation: pulse 1.4s ease-in-out infinite;
}}
.progress-stage.progress-done .progress-icon {{ color: {GOOD}; }}

@keyframes pulse {{
    0%, 100% {{ opacity: 1; transform: scale(1); }}
    50% {{ opacity: 0.5; transform: scale(1.15); }}
}}

/* ---------- DOCUMENT CARDS ---------- */
.doc-card {{
    background: {BG_RAISED};
    border: 1px solid {BORDER};
    border-radius: 10px;
    padding: 1.15rem 1.35rem;
    margin-bottom: 0.75rem;
    transition: border-color 0.12s ease;
}}
.doc-card:hover {{ border-color: {BORDER_HI}; }}
.doc-head {{
    display: flex; justify-content: space-between; align-items: flex-start;
    gap: 1rem; margin-bottom: 0.55rem;
}}
.doc-name {{
    font-size: 14.5px; color: {INK}; font-weight: 500;
    word-break: break-word; line-height: 1.35;
}}
.doc-meta {{
    font-size: 12px; color: {INK_FAINT};
    display: flex; flex-wrap: wrap; gap: 6px 14px;
}}
.doc-meta-item {{ display: inline-flex; align-items: center; gap: 5px; }}
.doc-error {{
    margin-top: 0.7rem; padding: 0.5rem 0.75rem;
    background: {BAD_BG}; border: 1px solid {BAD_BORDER}; border-radius: 6px;
    font-size: 12.5px; color: {BAD}; word-break: break-word;
}}

/* Status pills */
.pill {{
    display: inline-flex; align-items: center; gap: 6px;
    font-size: 11px; font-weight: 600; text-transform: uppercase;
    letter-spacing: 0.5px;
    padding: 4px 10px; border-radius: 999px;
    flex-shrink: 0;
}}
.pill-dot {{ width: 6px; height: 6px; border-radius: 50%; }}
.pill-ready {{ background: {GOOD_BG}; color: {GOOD}; border: 1px solid {GOOD_BORDER}; }}
.pill-ready .pill-dot {{ background: {GOOD}; box-shadow: 0 0 6px {GOOD}99; }}
.pill-processing {{ background: {WAIT}18; color: {WAIT}; border: 1px solid {WAIT}44; }}
.pill-processing .pill-dot {{ background: {WAIT}; animation: pulse 1.2s infinite; }}
.pill-uploaded {{ background: {BG}; color: {INK_MUTED}; border: 1px solid {BORDER_HI}; }}
.pill-uploaded .pill-dot {{ background: {INK_FAINT}; }}
.pill-failed {{ background: {BAD_BG}; color: {BAD}; border: 1px solid {BAD_BORDER}; }}
.pill-failed .pill-dot {{ background: {BAD}; }}


/* ---------- CHAT INPUT (wide, ChatGPT-style) ---------- */

/* Kill Streamlit's default flex shrink on the bottom bar so the input
   inherits full container width. */
[data-testid="stBottom"] > div {{
    background: transparent !important;
    padding: 0 !important;
}}

[data-testid="stBottomBlockContainer"] {{
    background: transparent !important;
    padding: 0 2.5rem 1.5rem 2.5rem !important;
    max-width: 100% !important;
    width: 100% !important;
}}

[data-testid="stChatInput"] {{
    background: {BG_RAISED} !important;
    border: 1px solid {BORDER_HI} !important;
    border-radius: 26px !important;
    padding: 8px 8px 8px 24px !important;
    box-shadow: 0 4px 16px rgba(20, 26, 31, 0.05),
                0 1px 0 rgba(255, 255, 255, 0.4) inset !important;
    width: 100% !important;
    max-width: 100% !important;
    margin: 0 !important;
    transition: border-color 0.18s ease, box-shadow 0.18s ease !important;
    overflow: visible !important;
}}

[data-testid="stChatInput"]:focus-within {{
    border-color: {BORDER_HI} !important;
    box-shadow: 0 8px 22px rgba(20, 26, 31, 0.08),
                0 1px 0 rgba(255, 255, 255, 0.5) inset !important;
}}

[data-testid="stChatInput"] textarea {{
    background: transparent !important;
    color: {INK} !important;
    font-size: 15px !important;
    font-family: 'Inter', -apple-system, sans-serif !important;
    line-height: 1.5 !important;
    padding: 12px 0 !important;
    min-height: 24px !important;
    border: none !important;
    outline: none !important;
    resize: none !important;
    box-shadow: none !important;
}}

[data-testid="stChatInput"] textarea::placeholder {{
    color: {INK_FAINT} !important;
    font-weight: 400 !important;
}}

[data-testid="stChatInput"] button,
[data-testid="stChatInputSubmitButton"] {{
    background: {BORDER} !important;
    color: {INK_MUTED} !important;
    border: none !important;
    border-radius: 50% !important;
    width: 38px !important;
    height: 38px !important;
    min-width: 38px !important;
    min-height: 38px !important;
    margin: 0 !important;
    padding: 0 !important;
    display: flex !important;
    align-items: center !important;
    justify-content: center !important;
    transition: background 0.15s ease, color 0.15s ease,
                transform 0.1s ease !important;
    flex-shrink: 0 !important;
    align-self: flex-end !important;
}}

[data-testid="stChatInput"] button:hover,
[data-testid="stChatInputSubmitButton"]:hover {{
    background: {BORDER_HI} !important;
    color: {INK} !important;
}}

[data-testid="stChatInput"] button:active,
[data-testid="stChatInputSubmitButton"]:active {{
    transform: scale(0.94) !important;
}}

[data-testid="stChatInput"] button svg,
[data-testid="stChatInputSubmitButton"] svg {{
    width: 17px !important;
    height: 17px !important;
}}

[data-testid="stChatInput"]:has(textarea:not(:placeholder-shown)) button,
[data-testid="stChatInput"]:has(textarea:not(:placeholder-shown))
    [data-testid="stChatInputSubmitButton"] {{
    background: {ACCENT} !important;
    color: {ACCENT_INK} !important;
}}

[data-testid="stChatInput"]:has(textarea:not(:placeholder-shown)) button:hover,
[data-testid="stChatInput"]:has(textarea:not(:placeholder-shown))
    [data-testid="stChatInputSubmitButton"]:hover {{
    background: {ACCENT_HI} !important;
    transform: scale(1.05) !important;
}}

/* Streamlit nests an inner wrapper inside stChatInput — make sure it
   doesn't add its own width constraint. */
[data-testid="stChatInput"] > div {{
    background: transparent !important;
    width: 100% !important;
    display: flex !important;
    align-items: flex-end !important;
    gap: 12px !important;
}}

[data-testid="stChatInput"] > div > div:first-child {{
    flex: 1 !important;
    min-width: 0 !important;
}}

/* ---------- UPLOAD ZONE ---------- */
[data-testid="stFileUploader"] {{
    background: {BG_RAISED} !important;
    border: 1px dashed {BORDER_HI} !important;
    border-radius: 12px !important;
    padding: 1rem !important;
    transition: border-color 0.15s ease !important;
    box-shadow: inset 0 0 0 1px rgba(255,255,255,0.35) !important;
}}
[data-testid="stFileUploader"]:hover {{ border-color: {ACCENT}66 !important; }}
[data-testid="stFileUploader"] section {{ background: transparent !important; border: none !important; }}
[data-testid="stFileUploader"] [data-testid="stMarkdownContainer"] p {{
    color: {INK} !important; font-size: 14px !important;
}}
[data-testid="stFileUploader"] button,
[data-testid="stFileUploader"] [data-testid="stBaseButton-secondary"],
[data-testid="stFileUploader"] [data-testid="baseButton-secondary"] {{
    background: #1b1f23 !important;
    color: #ffffff !important;
    border: 1px solid #2f363d !important;
    border-radius: 10px !important;
    font-weight: 600 !important;
    font-size: 14px !important;
    padding: 0.7rem 1.1rem !important;
    box-shadow: none !important;
}}
[data-testid="stFileUploader"] button:hover,
[data-testid="stFileUploader"] [data-testid="stBaseButton-secondary"]:hover,
[data-testid="stFileUploader"] [data-testid="baseButton-secondary"]:hover {{
    background: #2a2f34 !important;
    color: #ffffff !important;
}}

/* ---------- FORMS / INPUTS ---------- */
[data-testid="stTextInput"] input, [data-testid="stTextArea"] textarea {{
    background: {BG} !important; border: 1px solid {BORDER_HI} !important;
    color: {INK} !important; border-radius: 8px !important;
}}
[data-testid="stTextInput"] input:focus, [data-testid="stTextArea"] textarea:focus {{
    border-color: {ACCENT} !important;
    box-shadow: 0 0 0 3px {ACCENT}22 !important;
}}
[data-testid="stTextInput"] button,
[data-testid="stTextInput"] [data-testid="stBaseButton-secondary"],
[data-testid="stTextInput"] [data-testid="baseButton-secondary"],
[data-testid="stTextInput"] button[title*="Show password"],
[data-testid="stTextInput"] button[title*="Hide password"],
[data-testid="stTextInput"] button[aria-label*="Show password"],
[data-testid="stTextInput"] button[aria-label*="Hide password"] {{
    background: {BG_RAISED} !important;
    color: {INK} !important;
    border: 1px solid {BORDER_HI} !important;
    border-radius: 8px !important;
    font-size: 12px !important;
    font-weight: 600 !important;
    padding: 0.45rem 0.7rem !important;
    min-height: 0 !important;
    height: auto !important;
    box-shadow: none !important;
}}
[data-testid="stTextInput"] button:hover,
[data-testid="stTextInput"] [data-testid="stBaseButton-secondary"]:hover,
[data-testid="stTextInput"] [data-testid="baseButton-secondary"]:hover {{
    background: {BG_HOVER} !important;
    color: {INK} !important;
    border-color: {BORDER_HI} !important;
}}
[data-testid="stRadio"] label {{ color: {INK} !important; font-size: 14px !important; }}
[data-testid="stRadio"] [data-testid="stMarkdownContainer"] p {{
    color: {INK} !important; font-size: 14px !important;
}}

/* ---------- MISC ---------- */
[data-testid="stAlert"] {{
    background: {BG_RAISED} !important;
    border: 1px solid {BORDER_HI} !important;
    color: {INK} !important; border-radius: 10px !important;
}}
hr {{ border-color: {BORDER} !important; margin: 1.5rem 0 !important; }}
[data-testid="stCaptionContainer"] p {{ color: {INK_FAINT} !important; font-size: 13px !important; }}

::-webkit-scrollbar {{ width: 10px; height: 10px; }}
::-webkit-scrollbar-track {{ background: transparent; }}
::-webkit-scrollbar-thumb {{ background: {BORDER_HI}; border-radius: 5px; }}
::-webkit-scrollbar-thumb:hover {{ background: {INK_FAINT}; }}

/* Spinner (fallback) */
[data-testid="stSpinner"] > div {{ border-top-color: {ACCENT} !important; }}
</style>
"""


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


# ============================================================================
# SESSION STATE
# ============================================================================

def init_session():
    defaults = {
        "conversations": {},
        "current_conv_id": None,
        "session_id": str(uuid.uuid4()),
        "messages": [],
        "api_token": DEFAULT_TOKEN,
        "pipeline": "improved",
        "page": "Chat",
        "feedback_state": {},
        "pending_query": None,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


def _save_current_conversation():
    cid = st.session_state.current_conv_id
    if cid and cid in st.session_state.conversations:
        st.session_state.conversations[cid]["messages"] = list(st.session_state.messages)


def new_conversation():
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


def delete_conversation(cid: str):
    st.session_state.conversations.pop(cid, None)
    if cid == st.session_state.current_conv_id:
        st.session_state.current_conv_id = None
        st.session_state.messages = []
        st.session_state.session_id = str(uuid.uuid4())


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

        if st.button("＋  New conversation", use_container_width=True, key="new_conv_btn"):
            new_conversation()
            st.session_state.page = "Chat"
            st.rerun()

        # Group conversations by date
        convs = {cid: c for cid, c in st.session_state.conversations.items() if c["messages"]}
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
                        # Highlight active conversation via a scoped CSS rule
                        st.markdown(
                            f'<style>'
                            f'button[title="conversation:{cid}"]{{'
                            f'background:{BG}!important;color:{INK}!important;'
                            f'border-color:{BORDER_HI}!important;'
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
# NAV + HEADER
# ============================================================================

NAV_OPTIONS = ["Chat", "Upload", "Documents", "Settings"]


def render_sidebar_nav():
    """Simple vertical nav in the sidebar, above the conversation list."""
    with st.sidebar:
        current = st.session_state.page
        # We're inside a `with st.sidebar` already from render_sidebar; but
        # this function is called from main() directly. Caller context matters.
        pass  # handled inline in render_sidebar for simplicity below


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
    """Render the multi-stage progress card. Uses single-line HTML."""
    rows = ""
    for i, (label, _) in enumerate(stages):
        if i < current_idx:
            state, icon = "done", "✓"
        elif i == current_idx:
            state, icon = "active", "●"
        else:
            state, icon = "pending", "○"
        rows += (
            f'<div class="progress-stage progress-{state}">'
            f'<span class="progress-icon">{icon}</span>'
            f'<span class="progress-label">{esc(label)}</span>'
            f'</div>'
        )
    card = (
        '<div class="progress-card">'
        f'<div class="progress-header">'
        f'<span>Working</span>'
        f'<span class="progress-time">{elapsed:.0f}s</span>'
        f'</div>'
        f'{rows}'
        '</div>'
    )
    st.markdown(card, unsafe_allow_html=True)


def run_query_with_progress(prompt: str) -> tuple[dict | None, str | None]:
    """Execute a query in a background thread while showing staged progress.

    IMPORTANT: st.session_state is NOT thread-safe. All values the thread
    needs (pipeline, session_id, api_token) must be read on the main
    thread and passed in as arguments. The thread itself must not touch
    st.session_state.
    """
    # Capture everything the thread needs from session state NOW, on the
    # main thread, where session_state is valid.
    pipeline = st.session_state.pipeline
    session_id = st.session_state.session_id
    token = st.session_state.get("api_token", DEFAULT_TOKEN)

    result: dict = {}

    def _do_query():
        try:
            resp = requests.post(
                f"{API_BASE}/query",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                json={
                    "question": prompt,
                    "pipeline": pipeline,
                    "session_id": session_id,
                },
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
    slow_warned = False

    while t.is_alive():
        elapsed = time.time() - start

        # Figure out which stage we're likely in
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
            # Refresh the elapsed timer every ~1s
            if int(elapsed) != int(elapsed - 0.5):
                with placeholder.container():
                    _render_progress(STAGES, idx, elapsed)

        if elapsed > 60 and not slow_warned:
            slow_warned = True

        time.sleep(0.4)

    placeholder.empty()

    if "error" in result:
        return None, result["error"]
    return result.get("resp"), None


# ============================================================================
# MESSAGES
# ============================================================================

def render_user_message(text: str):
    st.markdown(
        f'<div class="user-row"><div class="user-bubble">{esc(text)}</div></div>',
        unsafe_allow_html=True,
    )


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
    block = (
        '<div class="sources-wrap">'
        f'<div class="sources-head">{count} {label}</div>'
        f'{items}'
        '</div>'
    )
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

    c1, c2, c3, _ = st.columns([1, 1, 1, 10], gap="small")
    with c1:
        if st.button("Useful", key=f"up_{msg_idx}"):
            _submit_feedback(msg, True, "")
            st.session_state.feedback_state[msg_idx] = "up"
            st.rerun()
    with c2:
        if st.button("Not useful", key=f"down_{msg_idx}"):
            st.session_state.feedback_state[msg_idx] = "pending_down"
            st.rerun()
    with c3:
        if st.button("Copy", key=f"copy_{msg_idx}"):
            st.session_state[f"copied_{msg_idx}"] = True
            st.toast("Copied — select the text above to paste")


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
    st.markdown(
        '<div class="asst-row">'
        '<div class="asst-avatar">K</div>'
        '<div class="asst-body">',
        unsafe_allow_html=True,
    )

    st.markdown(msg["content"])

    if msg.get("abstained"):
        st.markdown(
            '<div class="note note-abstain">⚠ &nbsp;No relevant evidence found in your documents.</div>',
            unsafe_allow_html=True,
        )

    rq = msg.get("resolved_query")
    if rq and rq != msg.get("original_question"):
        st.markdown(
            f'<div class="note note-rewrite">Searched as: <em>{esc(rq)}</em></div>',
            unsafe_allow_html=True,
        )

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
        '<div class="hero-sub">'
        'Ask about your PDFs, Word docs, or text files. '
        'Every answer shows where it came from.'
        '</div>'
        '</div>'
    )
    st.markdown(hero, unsafe_allow_html=True)

    st.markdown('<div class="examples-label">Some questions to start with</div>', unsafe_allow_html=True)

    # Two-column grid of example questions
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
    """Append the user message and mark the query as pending."""
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

    # Render all committed messages
    for i, msg in enumerate(st.session_state.messages):
        if msg["role"] == "user":
            render_user_message(msg["content"])
        else:
            render_assistant_message(msg, i)

    # Handle pending query with progress
    if st.session_state.pending_query:
        prompt = st.session_state.pending_query
        st.session_state.pending_query = None  # clear so we don't re-fire on rerun

        resp, error = run_query_with_progress(prompt)

        if error:
            st.session_state.messages.append({
                "role": "assistant",
                "content": f"Query failed: {error}",
                "citations": [],
                "abstained": False,
                "query": prompt,
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

        _save_current_conversation()
        st.rerun()

    # Chat input at the bottom
    prompt = st.chat_input("Ask a question…")
    if prompt:
        _send_query(prompt)
        st.rerun()
        st.markdown('<div style="height: 1rem;"></div>', unsafe_allow_html=True)
        st.markdown(
            '<div style="text-align:center;font-size:11.5px;color:#6a6357;margin-top:-6px;padding-bottom:8px;">'
            'The assistant answers only from your uploaded documents.'
            '</div>',
            unsafe_allow_html=True,
        )
            


# ============================================================================
# UPLOAD PAGE
# ============================================================================

def section_upload():
    render_page_header("Upload a document")
    st.caption("PDF, DOCX, TXT, or Markdown · up to 25 MB per file")

    uploaded = st.file_uploader(
        "Choose a file", type=["pdf", "docx", "txt", "md"],
        label_visibility="collapsed",
    )

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
            with st.spinner(f"Uploading {uploaded.name}…"):
                try:
                    files = {"file": (uploaded.name, uploaded.getvalue(), uploaded.type)}
                    data = {"metadata": _json.dumps(metadata)}
                    resp = api("POST", "/documents", files=files, data=data)
                except RuntimeError as e:
                    st.error(f"Upload failed: {e}")
                    resp = None

            if resp:
                doc_id = resp["id"]
                st.info(f"Uploaded. Processing **{uploaded.name}**…")
                progress = st.progress(0.0, text="Parsing and indexing…")
                done = False
                for i in range(90):
                    time.sleep(2)
                    progress.progress(min((i + 1) / 90, 1.0), text=f"Processing… ({i*2}s)")
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
    status_label = {
        "ready": "Ready",
        "processing": "Processing",
        "uploaded": "Queued",
        "failed": "Failed",
    }.get(status, status.capitalize())

    size_kb = d["size_bytes"] / 1024
    size_str = f"{size_kb:.1f} KB" if size_kb < 1024 else f"{size_kb/1024:.1f} MB"

    meta_items = [f'<span class="doc-meta-item">{size_str}</span>']
    if d.get("doc_metadata"):
        for k, v in d["doc_metadata"].items():
            meta_items.append(f'<span class="doc-meta-item">{esc(k)}: {esc(str(v))}</span>')
    created = (d.get("created_at") or "")[:10]
    if created:
        meta_items.append(f'<span class="doc-meta-item">{created}</span>')

    error_html = ""
    if d.get("failure_reason"):
        error_html = f'<div class="doc-error">{esc(d["failure_reason"])}</div>'

    card = (
        '<div class="doc-card">'
        '<div class="doc-head">'
        f'<div class="doc-name">{esc(d["filename"])}</div>'
        f'<span class="pill pill-{status}">'
        f'<span class="pill-dot"></span>{status_label}</span>'
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
            '<div class="hero-sub">Upload a PDF, DOCX, TXT, or Markdown file '
            'from the Upload tab and it will appear here.</div>'
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
            "Hybrid retrieval + reranking + multi-query + compression — slower, higher quality.",
            "Vector search only — fast baseline for comparison.",
        ],
        label_visibility="collapsed",
    )
    st.session_state.pipeline = pipeline

    st.markdown('<div class="side-label" style="margin-left:0; margin-top:2rem">Authentication</div>', unsafe_allow_html=True)
    token = st.text_input(
        "API bearer token",
        value=st.session_state.api_token,
        type="password",
        label_visibility="collapsed",
        placeholder="Bearer token",
    )
    if token != st.session_state.api_token:
        st.session_state.api_token = token
        st.rerun()

    st.markdown('<div class="side-label" style="margin-left:0; margin-top:2rem">Backend</div>', unsafe_allow_html=True)
    st.caption(f"`{API_BASE}`")
    if health_ok():
        st.success("Reachable — database ok")
    else:
        st.error("Unreachable or database down")


# ============================================================================
# MAIN
# ============================================================================

def main():
    st.set_page_config(
        page_title="Knowledge Base",
        page_icon="◆",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    st.markdown(CSS, unsafe_allow_html=True)
    init_session()

    render_sidebar()

    # Sidebar navigation (kept simple and vertical)
    with st.sidebar:
        st.markdown('<div class="side-label" style="margin-top:1.5rem">Navigate</div>', unsafe_allow_html=True)
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