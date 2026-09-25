"""
Design tokens + CSS for the Modern RAG Streamlit frontend.

Pulled out of app.py on purpose: app.py should read as "what the app
does", not "what the app looks like". Import inject_css() and call it
once at startup.

SIDEBAR CONTRAST FIX: Streamlit's theme engine sometimes writes an
inline style="background-color: ..." onto a nested wrapper div inside
the sidebar (dark-mode autodetection, or newer Streamlit versions that
add an extra stSidebarUserContent wrapper). An inline style beats a
class selector in an external stylesheet UNLESS that selector uses
!important. The previous CSS set `color` with !important but several
`background` rules did not -- dark text on dark background = invisible.

Fix:
  1. Every sidebar background rule carries !important.
  2. Rules repeat across every sidebar-wrapper testid Streamlit has
     used across versions (stSidebar / stSidebarContent /
     stSidebarUserContent), so the fix survives upgrades.
  3. Companion .streamlit/config.toml pins base="light" so the theme
     engine never injects a dark background in the first place.
"""

import streamlit as st

# ---------- design tokens ---------------------------------------------------
TOKENS = {
    "BG": "#ffffff",
    "BG_RAISED": "#f9f9f7",
    "BG_HOVER": "#f1f4f0",
    "BORDER": "#eceae4",
    "BORDER_HI": "#dfe3dc",
    "INK": "#17181a",
    "INK_MUTED": "#2f3740",
    "INK_FAINT": "#5d6670",
    "ACCENT": "#b7782d",
    "ACCENT_HI": "#a26620",
    "ACCENT_INK": "#ffffff",
    "GOOD": "#2d6d4b",
    "GOOD_BG": "#f0f9f4",
    "GOOD_BORDER": "#d9ebdf",
    "BAD": "#b0483d",
    "BAD_BG": "#fff4f2",
    "BAD_BORDER": "#f1d7d3",
    "WAIT": "#4a6ea8",
}


def _sidebar_selectors(inner: str) -> str:
    """Repeat a CSS body across every sidebar-wrapper testid Streamlit
    has used across versions, so the fix survives version upgrades."""
    roots = [
        '[data-testid="stSidebar"]',
        '[data-testid="stSidebarContent"]',
        '[data-testid="stSidebarUserContent"]',
    ]
    return "\n".join(f"{root} {inner}" for root in roots)


def get_css() -> str:
    t = TOKENS
    return f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Neuton:wght@400;500;600;700&family=Inter:wght@400;500;600;700&family=Fraunces:opsz,wght@9..144,500;9..144,600&display=swap');

.stApp {{ background: {t['BG']}; color: {t['INK']}; font-family: 'Neuton', 'Inter', -apple-system, sans-serif; }}
.stApp p, .stApp li, .stApp label, .stApp span, .stApp div, .stApp h1, .stApp h2, .stApp h3, .stApp h4, .stApp h5, .stApp h6 {{ color: inherit; }}
[data-testid="stHeader"] {{ background: transparent; height: 0; }}
section.main > div {{ padding-top: 0 !important; }}
.block-container {{ padding: 1.25rem 2.5rem 7rem 2.5rem !important; max-width: 100% !important; }}

/* ============================================================
   SIDEBAR -- background AND color both forced !important on
   every known wrapper testid. Fix for the invisible-text bug.
   ============================================================ */
{_sidebar_selectors('{ background-color: ' + t['BG_RAISED'] + ' !important; border-right: 1px solid ' + t['BORDER'] + ' !important; }')}

[data-testid="stSidebar"] * {{ color: {t['INK']} !important; }}
[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p,
[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] div,
[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] span {{
    color: {t['INK']} !important;
    background: transparent !important;
}}

[data-testid="stSidebar"] {{ width: 300px !important; }}
[data-testid="stSidebar"] .stButton > button,
button[title^="conversation:"] {{ box-shadow: none !important; }}
[data-testid="stSidebar"] > div:first-child {{ padding: 1.5rem 1.1rem !important; }}
[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p {{ margin: 0 !important; }}

.side-brand {{ padding: 0 0.2rem 1.1rem 0.2rem; border-bottom: 1px solid {t['BORDER']}; margin-bottom: 1.1rem; }}
.side-brand-name {{
    font-family: 'Fraunces', serif; font-weight: 600; font-size: 20px;
    color: {t['INK']} !important; letter-spacing: -0.2px;
}}
.side-brand-sub {{
    font-size: 11px; color: {t['INK_FAINT']} !important; margin-top: 5px;
    display: flex; align-items: center; gap: 6px; font-weight: 500;
}}
.side-brand-dot {{
    width: 6px; height: 6px; border-radius: 50%;
    background: {t['ACCENT']} !important; box-shadow: 0 0 8px {t['ACCENT']}99;
}}

[data-testid="stSidebar"] .stButton > button {{
    background: {t['BG']} !important;
    border: 1px solid {t['BORDER_HI']} !important;
    color: {t['INK']} !important;
    border-radius: 8px !important;
    font-size: 13.5px !important;
    font-weight: 500 !important;
    padding: 0.6rem 0.85rem !important;
    min-height: 0 !important;
    width: 100% !important;
    transition: all 0.12s ease !important;
}}
[data-testid="stSidebar"] .stButton > button:hover {{
    background: {t['BG_HOVER']} !important;
    border-color: {t['ACCENT']} !important;
    color: {t['ACCENT_HI']} !important;
}}

.side-label {{
    font-size: 11px; color: {t['INK_FAINT']} !important; font-weight: 600;
    margin: 1.4rem 0 0.5rem 0.3rem;
}}

[data-testid="stSidebar"] .stRadio {{ margin-top: 0.25rem; margin-bottom: 1.2rem; }}
[data-testid="stSidebar"] .stRadio > div {{ gap: 0.35rem !important; }}
[data-testid="stSidebar"] .stRadio label {{
    background: transparent !important;
    color: {t['INK_MUTED']} !important;
    font-size: 14px !important;
    font-weight: 500 !important;
    border-radius: 8px !important;
    padding: 0.38rem 0.55rem 0.38rem 0.45rem !important;
    transition: all 0.12s ease !important;
}}
[data-testid="stSidebar"] .stRadio label:hover {{
    background: {t['BG_HOVER']} !important;
    color: {t['INK']} !important;
}}
[data-testid="stSidebar"] .stRadio input[type="radio"] {{ accent-color: {t['ACCENT']} !important; }}
[data-testid="stSidebar"] .stRadio [data-testid="stMarkdownContainer"] p {{
    color: inherit !important; margin: 0 !important;
}}

[data-testid="stSidebar"] button[title^="conversation:"] {{
    background: transparent !important;
    border: 1px solid transparent !important;
    color: {t['INK_MUTED']} !important;
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
    background: {t['BG']} !important;
    color: {t['INK']} !important;
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
    color: {t['INK']}; letter-spacing: -0.3px; padding-top: 4px;
}}
.page-subtitle {{
    font-size: 12.5px; color: {t['INK_FAINT']}; padding-top: 8px;
    text-align: right; font-family: ui-monospace, monospace;
}}
.page-rule {{ border-bottom: 1px solid {t['BORDER']}; margin: 14px 0 1.75rem 0; }}

/* ---------- EMPTY STATE ---------- */
.hero {{ padding: 3rem 0 2.5rem 0; max-width: 640px; }}
.hero-title {{
    font-family: 'Fraunces', serif; font-size: 36px; font-weight: 500;
    color: {t['INK']}; line-height: 1.15; letter-spacing: -0.6px;
    margin-bottom: 0.9rem;
}}
.hero-title em {{ color: {t['ACCENT']}; font-style: italic; }}
.hero-sub {{ font-size: 15px; color: {t['INK_MUTED']}; line-height: 1.6; max-width: 480px; }}

.examples-label {{ font-size: 12px; color: {t['INK_FAINT']}; font-weight: 600; margin: 2.5rem 0 0.9rem 0; }}

button[title^="example:"] {{
    background: {t['BG_RAISED']} !important;
    border: 1px solid {t['BORDER']} !important;
    color: {t['INK_MUTED']} !important;
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
    background: {t['BG_HOVER']} !important;
    border-color: {t['ACCENT']} !important;
    color: {t['INK']} !important;
}}
button[title^="example:"] p {{ margin: 0 !important; text-align: left !important; font-size: 13px !important; color: inherit !important; }}
button[title^="example:"] > div {{ text-align: left !important; justify-content: flex-start !important; width: 100% !important; }}

/* ---------- MESSAGES ---------- */
.user-row {{ display: flex; justify-content: flex-end; margin: 2rem 0 1.25rem 0; }}
.user-bubble {{
    background: {t['BG_RAISED']}; border: 1px solid {t['BORDER']};
    padding: 12px 18px; border-radius: 14px 14px 4px 14px;
    max-width: 68%; color: {t['INK']}; font-size: 15px; line-height: 1.55;
}}

.asst-row {{ display: flex; gap: 16px; margin: 0 0 2.5rem 0; align-items: flex-start; }}
.asst-avatar {{
    width: 32px; height: 32px; flex-shrink: 0; margin-top: 2px;
    background: linear-gradient(135deg, {t['BG_RAISED']}, {t['BG']});
    border: 1px solid {t['BORDER_HI']};
    border-radius: 9px;
    display: flex; align-items: center; justify-content: center;
    color: {t['ACCENT']}; font-weight: 600; font-size: 14px;
    font-family: 'Fraunces', serif;
}}
.asst-body {{ flex: 1; min-width: 0; }}
.asst-body [data-testid="stMarkdownContainer"] p {{ color: {t['INK']}; font-size: 15.5px; line-height: 1.7; margin-bottom: 0.9em; }}
.asst-body [data-testid="stMarkdownContainer"] strong {{ color: {t['INK']}; font-weight: 700; }}
.asst-body [data-testid="stMarkdownContainer"] code {{
    background: {t['BG_RAISED']}; padding: 2px 7px; border-radius: 4px;
    font-size: 13px; color: {t['ACCENT_HI']}; border: 1px solid {t['BORDER']};
}}
.asst-body [data-testid="stMarkdownContainer"] ul,
.asst-body [data-testid="stMarkdownContainer"] ol {{ margin-top: 0.4em; margin-bottom: 0.9em; }}
.asst-body [data-testid="stMarkdownContainer"] li {{ color: {t['INK']}; font-size: 15.5px; line-height: 1.7; margin-bottom: 0.4em; }}
.asst-body [data-testid="stMarkdownContainer"] a {{ color: {t['ACCENT_HI']}; text-decoration: none; border-bottom: 1px solid {t['ACCENT']}55; }}

/* ---------- CITATIONS ---------- */
.sources-wrap {{ margin-top: 1.4rem; }}
.sources-head {{
    display: flex; align-items: center; gap: 10px;
    padding: 0.7rem 0 0.6rem 0; border-bottom: 1px solid {t['BORDER']};
    font-size: 12px; color: {t['INK_FAINT']}; font-weight: 600;
}}
.source-item {{ display: flex; gap: 14px; padding: 0.95rem 0; border-bottom: 1px solid {t['BORDER']}; }}
.source-num {{
    flex-shrink: 0; width: 24px; height: 24px;
    background: {t['BG_RAISED']}; border: 1px solid {t['BORDER_HI']};
    border-radius: 6px; display: flex; align-items: center; justify-content: center;
    font-size: 11px; font-weight: 600; color: {t['ACCENT']};
    font-family: ui-monospace, monospace;
}}
.source-body {{ flex: 1; min-width: 0; }}
.source-file {{ font-size: 13px; color: {t['INK']}; font-weight: 500; margin-bottom: 4px; }}
.source-file .source-meta {{ color: {t['INK_FAINT']}; font-weight: 400; margin-left: 8px; }}
.source-file .source-score {{ color: {t['INK_FAINT']}; font-family: ui-monospace, monospace; font-size: 11px; margin-left: 8px; }}
.source-excerpt {{
    font-size: 13px; color: {t['INK_MUTED']}; line-height: 1.6;
    display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical;
    overflow: hidden;
}}

/* ---------- STATUS NOTES ---------- */
.note {{ display: inline-flex; align-items: center; gap: 8px; padding: 6px 12px; border-radius: 6px; font-size: 12.5px; font-weight: 500; margin-top: 0.9rem; }}
.note-abstain {{ background: {t['ACCENT']}10; border: 1px solid {t['ACCENT']}44; color: {t['ACCENT_HI']}; }}
.note-rewrite {{ background: transparent; border: none; color: {t['INK_FAINT']}; font-size: 12px; font-weight: 400; padding: 4px 0; }}
.note-rewrite em {{ color: {t['INK_MUTED']}; font-style: normal; }}
.note-useful {{ background: {t['GOOD_BG']}; border: 1px solid {t['GOOD_BORDER']}; color: {t['GOOD']}; }}
.note-notuseful {{ background: {t['BAD_BG']}; border: 1px solid {t['BAD_BORDER']}; color: {t['BAD']}; }}

/* ---------- MESSAGE ACTIONS ---------- */
[data-testid="stHorizontalBlock"] button[kind="secondary"] {{
    background: transparent !important;
    border: 1px solid {t['BORDER']} !important;
    color: {t['INK_MUTED']} !important;
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
    background: {t['BG_RAISED']} !important;
    border-color: {t['BORDER_HI']} !important;
    color: {t['INK']} !important;
}}

button[kind="primary"] {{
    background: {t['ACCENT']} !important;
    color: {t['ACCENT_INK']} !important;
    border: 1px solid {t['ACCENT']} !important;
    border-radius: 8px !important;
    font-weight: 600 !important;
    font-size: 14px !important;
    padding: 0.6rem 1.5rem !important;
}}
button[kind="primary"]:hover {{ background: {t['ACCENT_HI']} !important; border-color: {t['ACCENT_HI']} !important; }}

/* ---------- PROGRESS CARD ---------- */
.progress-card {{ background: {t['BG_RAISED']}; border: 1px solid {t['BORDER']}; border-radius: 12px; padding: 1.25rem 1.5rem; margin: 1.5rem 0; max-width: 480px; }}
.progress-header {{ font-size: 12px; color: {t['INK_FAINT']}; font-weight: 500; margin-bottom: 1rem; display: flex; justify-content: space-between; align-items: center; }}
.progress-time {{ font-family: ui-monospace, monospace; color: {t['INK_MUTED']}; }}
.progress-stage {{ display: flex; align-items: center; gap: 12px; padding: 0.45rem 0; font-size: 14px; color: {t['INK_FAINT']}; }}
.progress-stage.progress-active {{ color: {t['INK']}; }}
.progress-stage.progress-done {{ color: {t['INK_MUTED']}; }}
.progress-icon {{ flex-shrink: 0; width: 20px; height: 20px; display: flex; align-items: center; justify-content: center; font-size: 12px; }}
.progress-stage.progress-pending .progress-icon {{ color: {t['INK_FAINT']}; }}
.progress-stage.progress-active .progress-icon {{ color: {t['ACCENT']}; animation: pulse 1.4s ease-in-out infinite; }}
.progress-stage.progress-done .progress-icon {{ color: {t['GOOD']}; }}

@keyframes pulse {{ 0%, 100% {{ opacity: 1; transform: scale(1); }} 50% {{ opacity: 0.5; transform: scale(1.15); }} }}

/* ---------- DOCUMENT CARDS ---------- */
.doc-card {{ background: {t['BG_RAISED']}; border: 1px solid {t['BORDER']}; border-radius: 10px; padding: 1.15rem 1.35rem; margin-bottom: 0.75rem; transition: border-color 0.12s ease; }}
.doc-card:hover {{ border-color: {t['BORDER_HI']}; }}
.doc-head {{ display: flex; justify-content: space-between; align-items: flex-start; gap: 1rem; margin-bottom: 0.55rem; }}
.doc-name {{ font-size: 14.5px; color: {t['INK']}; font-weight: 500; word-break: break-word; line-height: 1.35; }}
.doc-meta {{ font-size: 12px; color: {t['INK_FAINT']}; display: flex; flex-wrap: wrap; gap: 6px 14px; }}
.doc-meta-item {{ display: inline-flex; align-items: center; gap: 5px; }}
.doc-error {{ margin-top: 0.7rem; padding: 0.5rem 0.75rem; background: {t['BAD_BG']}; border: 1px solid {t['BAD_BORDER']}; border-radius: 6px; font-size: 12.5px; color: {t['BAD']}; word-break: break-word; }}

.pill {{ display: inline-flex; align-items: center; gap: 6px; font-size: 11.5px; font-weight: 600; padding: 4px 10px; border-radius: 999px; flex-shrink: 0; }}
.pill-dot {{ width: 6px; height: 6px; border-radius: 50%; }}
.pill-ready {{ background: {t['GOOD_BG']}; color: {t['GOOD']}; border: 1px solid {t['GOOD_BORDER']}; }}
.pill-ready .pill-dot {{ background: {t['GOOD']}; box-shadow: 0 0 6px {t['GOOD']}99; }}
.pill-processing {{ background: {t['WAIT']}18; color: {t['WAIT']}; border: 1px solid {t['WAIT']}44; }}
.pill-processing .pill-dot {{ background: {t['WAIT']}; animation: pulse 1.2s infinite; }}
.pill-uploaded {{ background: {t['BG']}; color: {t['INK_MUTED']}; border: 1px solid {t['BORDER_HI']}; }}
.pill-uploaded .pill-dot {{ background: {t['INK_FAINT']}; }}
.pill-failed {{ background: {t['BAD_BG']}; color: {t['BAD']}; border: 1px solid {t['BAD_BORDER']}; }}
.pill-failed .pill-dot {{ background: {t['BAD']}; }}

/* ---------- CHAT INPUT ---------- */
[data-testid="stBottom"] > div {{ background: transparent !important; padding: 0 !important; }}
[data-testid="stBottomBlockContainer"] {{ background: transparent !important; padding: 0 2.5rem 1.5rem 2.5rem !important; max-width: 100% !important; width: 100% !important; }}
[data-testid="stChatInput"] {{
    background: {t['BG_RAISED']} !important;
    border: 1px solid {t['BORDER_HI']} !important;
    border-radius: 26px !important;
    padding: 8px 8px 8px 24px !important;
    box-shadow: 0 4px 16px rgba(20, 26, 31, 0.05), 0 1px 0 rgba(255, 255, 255, 0.4) inset !important;
    width: 100% !important; max-width: 100% !important; margin: 0 !important;
    transition: border-color 0.18s ease, box-shadow 0.18s ease !important;
    overflow: visible !important;
}}
[data-testid="stChatInput"]:focus-within {{
    border-color: {t['BORDER_HI']} !important;
    box-shadow: 0 8px 22px rgba(20, 26, 31, 0.08), 0 1px 0 rgba(255, 255, 255, 0.5) inset !important;
}}
[data-testid="stChatInput"] textarea {{
    background: transparent !important; color: {t['INK']} !important;
    font-size: 15px !important; font-family: 'Inter', -apple-system, sans-serif !important;
    line-height: 1.5 !important; padding: 12px 0 !important; min-height: 24px !important;
    border: none !important; outline: none !important; resize: none !important; box-shadow: none !important;
}}
[data-testid="stChatInput"] textarea::placeholder {{ color: {t['INK_FAINT']} !important; font-weight: 400 !important; }}
[data-testid="stChatInput"] button,
[data-testid="stChatInputSubmitButton"] {{
    background: {t['BORDER']} !important; color: {t['INK_MUTED']} !important;
    border: none !important; border-radius: 50% !important;
    width: 38px !important; height: 38px !important; min-width: 38px !important; min-height: 38px !important;
    margin: 0 !important; padding: 0 !important;
    display: flex !important; align-items: center !important; justify-content: center !important;
    transition: background 0.15s ease, color 0.15s ease, transform 0.1s ease !important;
    flex-shrink: 0 !important; align-self: flex-end !important;
}}
[data-testid="stChatInput"] button:hover,
[data-testid="stChatInputSubmitButton"]:hover {{ background: {t['BORDER_HI']} !important; color: {t['INK']} !important; }}
[data-testid="stChatInput"] button:active,
[data-testid="stChatInputSubmitButton"]:active {{ transform: scale(0.94) !important; }}
[data-testid="stChatInput"] button svg,
[data-testid="stChatInputSubmitButton"] svg {{ width: 17px !important; height: 17px !important; }}
[data-testid="stChatInput"]:has(textarea:not(:placeholder-shown)) button,
[data-testid="stChatInput"]:has(textarea:not(:placeholder-shown)) [data-testid="stChatInputSubmitButton"] {{
    background: {t['ACCENT']} !important; color: {t['ACCENT_INK']} !important;
}}
[data-testid="stChatInput"]:has(textarea:not(:placeholder-shown)) button:hover,
[data-testid="stChatInput"]:has(textarea:not(:placeholder-shown)) [data-testid="stChatInputSubmitButton"]:hover {{
    background: {t['ACCENT_HI']} !important; transform: scale(1.05) !important;
}}
[data-testid="stChatInput"] > div {{ background: transparent !important; width: 100% !important; display: flex !important; align-items: flex-end !important; gap: 12px !important; }}
[data-testid="stChatInput"] > div > div:first-child {{ flex: 1 !important; min-width: 0 !important; }}

.chat-disclaimer {{ text-align: center; font-size: 11.5px; color: {t['INK_FAINT']}; margin-top: 0.6rem; padding-bottom: 4px; }}

/* ---------- UPLOAD ZONE ---------- */
[data-testid="stFileUploader"] {{
    background: #f5f4f2 !important; border: 1px solid {t['BORDER']} !important;
    border-radius: 12px !important; padding: 0.75rem 1rem !important;
    transition: border-color 0.15s ease !important; box-shadow: none !important;
}}
[data-testid="stFileUploader"]:hover {{ border-color: {t['BORDER_HI']} !important; }}
[data-testid="stFileUploader"] section {{ background: transparent !important; border: none !important; }}
[data-testid="stFileUploader"] > div {{ display: flex !important; align-items: center !important; justify-content: space-between !important; gap: 0.9rem !important; }}
[data-testid="stFileUploader"] * {{ color: {t['INK']} !important; }}
[data-testid="stFileUploader"] [data-testid="stMarkdownContainer"] p {{ color: {t['INK']} !important; font-size: 14px !important; margin: 0 !important; }}
[data-testid="stFileUploader"] button,
[data-testid="stFileUploader"] [data-testid="stBaseButton-secondary"],
[data-testid="stFileUploader"] [data-testid="baseButton-secondary"] {{
    background: #1b1f23 !important; color: #ffffff !important; border: 1px solid #1b1f23 !important;
    border-radius: 8px !important; font-weight: 600 !important; font-size: 14px !important;
    padding: 0.55rem 1rem !important; box-shadow: none !important; margin-left: auto !important;
}}
[data-testid="stFileUploader"] button:hover,
[data-testid="stFileUploader"] [data-testid="stBaseButton-secondary"]:hover,
[data-testid="stFileUploader"] [data-testid="baseButton-secondary"]:hover {{ background: #2a2f34 !important; color: #ffffff !important; }}

/* ---------- FORMS / INPUTS ---------- */
[data-testid="stTextInput"] input, [data-testid="stTextArea"] textarea {{
    background: {t['BG']} !important; border: 1px solid {t['BORDER_HI']} !important;
    color: {t['INK']} !important; border-radius: 8px !important;
}}
[data-testid="stTextInput"] input:focus, [data-testid="stTextArea"] textarea:focus {{
    border-color: {t['ACCENT']} !important; box-shadow: 0 0 0 3px {t['ACCENT']}22 !important;
}}
[data-testid="stTextInput"] button,
[data-testid="stTextInput"] [data-testid="stBaseButton-secondary"],
[data-testid="stTextInput"] [data-testid="baseButton-secondary"],
[data-testid="stTextInput"] button[title*="Show password"],
[data-testid="stTextInput"] button[title*="Hide password"],
[data-testid="stTextInput"] button[aria-label*="Show password"],
[data-testid="stTextInput"] button[aria-label*="Hide password"] {{
    background: {t['BG_RAISED']} !important; color: {t['INK']} !important;
    border: 1px solid {t['BORDER_HI']} !important; border-radius: 8px !important;
    font-size: 12px !important; font-weight: 600 !important; padding: 0.45rem 0.7rem !important;
    min-height: 0 !important; height: auto !important; box-shadow: none !important;
}}
[data-testid="stTextInput"] button:hover,
[data-testid="stTextInput"] [data-testid="stBaseButton-secondary"]:hover,
[data-testid="stTextInput"] [data-testid="baseButton-secondary"]:hover {{
    background: {t['BG_HOVER']} !important; color: {t['INK']} !important; border-color: {t['BORDER_HI']} !important;
}}
[data-testid="stRadio"] label {{ color: {t['INK']} !important; font-size: 14px !important; }}
[data-testid="stRadio"] [data-testid="stMarkdownContainer"] p {{ color: {t['INK']} !important; font-size: 14px !important; }}

/* ---------- MISC ---------- */
[data-testid="stAlert"] {{ background: {t['BG_RAISED']} !important; border: 1px solid {t['BORDER_HI']} !important; color: {t['INK']} !important; border-radius: 10px !important; }}
hr {{ border-color: {t['BORDER']} !important; margin: 1.5rem 0 !important; }}
[data-testid="stCaptionContainer"] p {{ color: {t['INK_FAINT']} !important; font-size: 13px !important; }}

::-webkit-scrollbar {{ width: 10px; height: 10px; }}
::-webkit-scrollbar-track {{ background: transparent; }}
::-webkit-scrollbar-thumb {{ background: {t['BORDER_HI']}; border-radius: 5px; }}
::-webkit-scrollbar-thumb:hover {{ background: {t['INK_FAINT']}; }}

[data-testid="stSpinner"] > div {{ border-top-color: {t['ACCENT']} !important; }}
</style>
"""


def inject_css() -> None:
    st.markdown(get_css(), unsafe_allow_html=True)