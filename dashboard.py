"""RecallFabric - Claude-inspired dark mode chatbot with live memory sidebar."""

import html
import json
import os

import streamlit as st

from recallfabric.dashboard_client import (
    DashboardClientError,
    chat_with_service,
    check_status,
    clear_all_memories,
    create_api_key,
    create_memory,
    delete_all_user_memories,
    delete_memory,
    disable_memory,
    enable_memory,
    export_user_data,
    fetch_memories,
    get_memory,
    get_memory_history,
    get_memory_provenance,
    list_api_keys,
    preview_extraction,
    retrieve_memories,
    revoke_api_key,
    search_memories,
    signup_user,
    update_memory,
)

API_URL = os.getenv("RECALLFABRIC_API_URL", "http://127.0.0.1:8000")
OLLAMA_URL = os.getenv(
    "RECALLFABRIC_LLM_BASE_URL", os.getenv("OLLAMA_URL", "http://127.0.0.1:11434/v1")
)
MODEL = os.getenv("RECALLFABRIC_CHAT_MODEL", os.getenv("MODEL", "qwen2.5:0.5b"))
USER_ID = os.getenv("RECALLFABRIC_USER_ID", "demo_user")
LLM_API_KEY = os.getenv("RECALLFABRIC_LLM_API_KEY", "ollama")
API_KEY = os.getenv("RECALLFABRIC_API_KEY", "")

st.set_page_config(
    page_title="RecallFabric", page_icon="🧠", layout="wide", initial_sidebar_state="expanded"
)

st.markdown(
    """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');

* {
    box-sizing: border-box;
}

html, body, [class*="css"] {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    color: #ECECED;
}

/* ── Custom Dark Scrollbars ── */
::-webkit-scrollbar {
    width: 6px;
    height: 6px;
}
::-webkit-scrollbar-track {
    background: transparent;
}
::-webkit-scrollbar-thumb {
    background: rgba(255, 255, 255, 0.15);
    border-radius: 4px;
}
::-webkit-scrollbar-thumb:hover {
    background: rgba(255, 255, 255, 0.25);
}

/* ── App Canvas: Claude Matte Dark Slate ── */
.stApp {
    background-color: #1E1F22 !important;
    color: #ECECED !important;
}

header[data-testid="stHeader"] {
    background-color: transparent !important;
}

/* ── Sidebar: Deep Charcoal (#171719) ── */
[data-testid="stSidebar"] {
    background-color: #171719 !important;
    border-right: 1px solid rgba(255, 255, 255, 0.07) !important;
}
[data-testid="stSidebar"] > div:first-child {
    background-color: #171719 !important;
}
[data-testid="stSidebar"] * {
    color: #ECECED;
}
[data-testid="stSidebar"] hr {
    border-color: rgba(255, 255, 255, 0.08) !important;
    margin: 1rem 0 !important;
}

/* Sidebar branding */
.sb-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 0.25rem;
}
.sb-title {
    font-size: 0.82rem;
    font-weight: 700;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    color: #E4E4E7;
}
.sb-user-pill {
    background: rgba(255, 255, 255, 0.06);
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 6px;
    padding: 2px 7px;
    font-size: 0.72rem;
    font-family: monospace;
    color: #A1A1AA;
}

/* Status pills */
.status-bar {
    display: flex;
    gap: 8px;
    margin: 0.6rem 0 1rem 0;
}
.status-pill {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    background: rgba(255, 255, 255, 0.04);
    border: 1px solid rgba(255, 255, 255, 0.07);
    border-radius: 6px;
    padding: 3px 8px;
    font-size: 0.74rem;
    color: #A1A1AA;
}
.dot-ok   { color: #4ADE80; font-weight: 700; }
.dot-fail { color: #F87171; font-weight: 700; }

/* Sidebar action buttons */
[data-testid="stSidebar"] .stButton > button {
    background: #242428 !important;
    border: 1px solid rgba(255, 255, 255, 0.1) !important;
    color: #ECECED !important;
    border-radius: 8px !important;
    font-size: 0.82rem !important;
    font-weight: 500 !important;
    padding: 0.4rem 0.75rem !important;
    transition: all 0.15s ease !important;
}
[data-testid="stSidebar"] .stButton > button:hover {
    background: #2E2E34 !important;
    border-color: rgba(255, 255, 255, 0.22) !important;
    color: #FFFFFF !important;
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.25) !important;
}

/* Sidebar memory cards */
.mem-card {
    background: #222226;
    border: 1px solid rgba(255, 255, 255, 0.07);
    border-radius: 10px;
    padding: 10px 12px;
    margin-bottom: 8px;
    box-shadow: 0 2px 6px rgba(0, 0, 0, 0.18);
    transition: all 0.15s ease;
}
.mem-card:hover {
    background: #27272C;
    border-color: rgba(255, 255, 255, 0.14);
}
.mem-tag-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 4px;
}
.mem-tag {
    font-size: 0.62rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: #E5B869;
}
.mem-text {
    font-size: 0.84rem;
    color: #F3F4F6;
    line-height: 1.45;
}
.mem-meta {
    font-size: 0.66rem;
    color: #71717A;
    margin-top: 5px;
}
.badge-new {
    background: #E5B869;
    color: #171719;
    font-size: 0.55rem;
    font-weight: 800;
    padding: 1px 6px;
    border-radius: 99px;
    letter-spacing: 0.07em;
    text-transform: uppercase;
}

/* ── Main content area ── */
.block-container {
    max-width: 960px !important;
    padding-top: 1.5rem !important;
    padding-bottom: 7rem !important;
    padding-left: 2rem !important;
    padding-right: 2rem !important;
    margin: 0 auto;
    background: transparent !important;
}

/* ── Tabs Styling: Claude Minimal Dark Theme ── */
.stTabs [data-baseweb="tab-list"] {
    background-color: #171719;
    border-radius: 10px;
    padding: 4px;
    gap: 8px;
    border: 1px solid rgba(255, 255, 255, 0.08);
    margin-bottom: 1.5rem;
}
.stTabs [data-baseweb="tab"] {
    color: #A1A1AA !important;
    border-radius: 8px;
    padding: 6px 18px;
    font-size: 0.88rem;
    font-weight: 500;
}
.stTabs [aria-selected="true"] {
    background-color: #242429 !important;
    color: #FFFFFF !important;
    border-bottom: 2px solid #E5B869 !important;
}

/* ── Header: Claude Minimal Dark Style ── */
.rf-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 1.5rem;
    padding-bottom: 1rem;
    border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}
.rf-brand {
    display: flex;
    align-items: center;
    gap: 12px;
}
.rf-avatar {
    font-size: 1.6rem;
    background: rgba(229, 184, 105, 0.12);
    border: 1px solid rgba(229, 184, 105, 0.25);
    border-radius: 12px;
    width: 42px;
    height: 42px;
    display: flex;
    align-items: center;
    justify-content: center;
}
.rf-title {
    font-size: 1.25rem;
    font-weight: 600;
    color: #FFFFFF;
    letter-spacing: -0.02em;
}
.rf-subtitle {
    font-size: 0.76rem;
    color: #9CA3AF;
    margin-top: 2px;
}
.rf-badge {
    background: rgba(74, 222, 128, 0.1);
    border: 1px solid rgba(74, 222, 128, 0.25);
    color: #4ADE80;
    font-size: 0.72rem;
    font-weight: 600;
    padding: 4px 10px;
    border-radius: 99px;
    letter-spacing: 0.04em;
}

/* ── User Message Card: Claude Style ── */
.user-msg-row {
    display: flex;
    justify-content: flex-end;
    width: 100%;
    margin-top: 1.2rem;
    margin-bottom: 1.4rem;
}
.user-msg-card {
    background-color: #2A2A2E;
    border: 1px solid rgba(255, 255, 255, 0.09);
    border-radius: 14px;
    padding: 13px 18px;
    color: #ECECED;
    font-size: 0.94rem;
    line-height: 1.6;
    max-width: 82%;
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.22);
    word-break: break-word;
}

/* ── Assistant Message: Clean Text Directly on Canvas ── */
[data-testid="stChatMessage"] {
    background: transparent !important;
    border: none !important;
    padding: 0 !important;
    margin-bottom: 1.5rem !important;
}
[data-testid="stChatMessage"] .stAvatar,
[data-testid*="ChatMessageAvatar"],
[data-testid*="chatAvatar"],
div[class*="stChatMessageAvatar"] {
    display: none !important;
}
[data-testid="stChatMessage"] [data-testid="stChatMessageContent"] {
    background: transparent !important;
    border: none !important;
    padding: 0 !important;
    color: #ECECED !important;
}

/* ── Typography & Markdown Contrast ── */
.stMarkdown, .stMarkdown p, .stMarkdown span, .stMarkdown div {
    color: #ECECED !important;
    font-size: 0.95rem;
    line-height: 1.68;
}
.stMarkdown h1, .stMarkdown h2, .stMarkdown h3, .stMarkdown h4 {
    color: #FFFFFF !important;
    font-weight: 600 !important;
    margin-top: 1rem !important;
    margin-bottom: 0.5rem !important;
}
.stMarkdown strong, .stMarkdown b {
    color: #FFFFFF !important;
    font-weight: 600 !important;
}
.stMarkdown ul, .stMarkdown ol {
    color: #ECECED !important;
    padding-left: 1.25rem !important;
    margin-top: 0.5rem !important;
    margin-bottom: 0.5rem !important;
}
.stMarkdown li {
    color: #ECECED !important;
    line-height: 1.65 !important;
    margin-bottom: 0.35rem !important;
}
.stMarkdown code {
    background: #2A2A2E !important;
    color: #E5B869 !important;
    padding: 2px 6px !important;
    border-radius: 4px !important;
    font-size: 0.88em !important;
    border: 1px solid rgba(255, 255, 255, 0.08) !important;
}
.stMarkdown pre {
    background: #171719 !important;
    border: 1px solid rgba(255, 255, 255, 0.1) !important;
    border-radius: 8px !important;
    padding: 12px 16px !important;
}
.stMarkdown pre code {
    background: transparent !important;
    border: none !important;
    color: #ECECED !important;
}

/* ── Memory Expander (Retrieved context) ── */
[data-testid="stExpander"] {
    background-color: #242429 !important;
    border: 1px solid rgba(255, 255, 255, 0.08) !important;
    border-radius: 10px !important;
    overflow: hidden;
    margin-top: 8px !important;
    margin-bottom: 12px !important;
}
[data-testid="stExpander"] summary {
    color: #E5B869 !important;
    font-size: 0.82rem !important;
    font-weight: 500 !important;
    padding: 8px 12px !important;
}
[data-testid="stExpander"] summary:hover {
    color: #F3C97C !important;
}
[data-testid="stExpander"] [data-testid="stExpanderDetails"] {
    padding: 8px 12px 12px 12px !important;
    border-top: 1px solid rgba(255, 255, 255, 0.05) !important;
}
.ctx-box {
    background: rgba(229, 184, 105, 0.08);
    border-left: 3px solid #E5B869;
    border-radius: 6px;
    padding: 8px 12px;
    margin-top: 6px;
    font-size: 0.82rem;
    color: #F3F4F6;
    line-height: 1.5;
}

/* ── Floating Claude Bottom Chat Input ── */
[data-testid="stBottom"] {
    background-color: #1E1F22 !important;
    border-top: none !important;
}
[data-testid="stBottom"] > div {
    background-color: transparent !important;
}
[data-testid="stChatInput"] {
    background: #28282D !important;
    border: 1px solid rgba(255, 255, 255, 0.12) !important;
    border-radius: 16px !important;
    box-shadow: 0 4px 20px rgba(0, 0, 0, 0.35) !important;
    transition: all 0.15s ease !important;
    padding: 2px 6px !important;
}
[data-testid="stChatInput"]:focus-within {
    border-color: rgba(255, 255, 255, 0.25) !important;
    box-shadow: 0 0 0 1px rgba(255, 255, 255, 0.15), 0 4px 24px rgba(0, 0, 0, 0.45) !important;
}
[data-testid="stChatInput"] textarea {
    background: transparent !important;
    color: #ECECED !important;
    font-size: 0.94rem !important;
    line-height: 1.5 !important;
}
[data-testid="stChatInput"] textarea::placeholder {
    color: #71717A !important;
}
[data-testid="stChatInput"] button {
    color: #ECECED !important;
    background: rgba(255, 255, 255, 0.08) !important;
    border-radius: 8px !important;
}
[data-testid="stChatInput"] button:hover {
    background: rgba(255, 255, 255, 0.16) !important;
}

/* Thinking status text */
.thinking {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    font-size: 0.82rem;
    color: #A1A1AA;
    font-style: italic;
}
.thinking::before {
    content: "●";
    color: #E5B869;
    animation: rf-pulse 1.4s infinite;
}
@keyframes rf-pulse {
    0%, 100% { opacity: 0.3; }
    50% { opacity: 1; }
}

.sidebar-disclaimer {
    font-size: 0.68rem;
    color: #6B7280;
    line-height: 1.4;
    margin-top: 1.5rem;
    text-align: center;
    border-top: 1px solid rgba(255, 255, 255, 0.06);
    padding-top: 0.8rem;
}
</style>
""",
    unsafe_allow_html=True,
)


def render_user_message(content: str):
    escaped = html.escape(content).replace("\n", "<br>")
    st.markdown(
        f'<div class="user-msg-row"><div class="user-msg-card">{escaped}</div></div>',
        unsafe_allow_html=True,
    )


def render_assistant_message(content: str, retrieved=None):
    with st.chat_message("assistant"):
        st.markdown(content)
        if retrieved:
            with st.expander("🧠 Memory context used"):
                for item in retrieved:
                    st.markdown(
                        f'<div class="ctx-box">📌 {item["content"]}</div>',
                        unsafe_allow_html=True,
                    )


if "messages" not in st.session_state:
    st.session_state.messages = []
if "memories" not in st.session_state:
    try:
        st.session_state.memories = fetch_memories(API_URL, USER_ID, limit=50)
    except Exception:
        st.session_state.memories = []
if "new_ids" not in st.session_state:
    st.session_state.new_ids = set()
if "confirm_clear_all" not in st.session_state:
    st.session_state.confirm_clear_all = False
if "memories_page" not in st.session_state:
    st.session_state.memories_page = 0


with st.sidebar:
    st.markdown(
        """
    <div class="sb-header">
        <span class="sb-title">🧠 Memory Stream</span>
        <span class="sb-user-pill">demo_user</span>
    </div>
    """,
        unsafe_allow_html=True,
    )

    api_ok, ollama_ok = check_status(API_URL, OLLAMA_URL)
    a_dot = '<span class="dot-ok">●</span> API' if api_ok else '<span class="dot-fail">○</span> API'
    o_dot = (
        '<span class="dot-ok">●</span> Ollama'
        if ollama_ok
        else '<span class="dot-fail">○</span> Ollama'
    )
    st.markdown(
        f"""
    <div class="status-bar">
        <span class="status-pill">{a_dot}</span>
        <span class="status-pill">{o_dot}</span>
    </div>
    """,
        unsafe_allow_html=True,
    )

    c1, c2 = st.columns(2)
    with c1:
        if st.button("↻ Refresh", use_container_width=True):
            try:
                st.session_state.memories = fetch_memories(API_URL, USER_ID, limit=50)
            except Exception:
                pass
            st.session_state.new_ids = set()
            st.rerun()
    with c2:
        if st.button("✕ Clear", use_container_width=True):
            st.session_state.confirm_clear_all = True

    if st.session_state.confirm_clear_all:
        st.warning("Clear all memories for this user?")
        cyes, cno = st.columns(2)
        with cyes:
            if st.button("Yes, Clear", key="sb_confirm_yes", use_container_width=True):
                ok, result = clear_all_memories(API_URL, USER_ID)
                st.session_state.confirm_clear_all = False
                if ok:
                    st.session_state.memories = []
                    st.session_state.new_ids = set()
                    st.rerun()
                else:
                    st.error(str(result))
        with cno:
            if st.button("Cancel", key="sb_confirm_no", use_container_width=True):
                st.session_state.confirm_clear_all = False
                st.rerun()

    st.markdown("---")

    memories = st.session_state.memories
    if not memories:
        st.caption("No memories yet. Chat with the AI to teach it!")
    else:
        st.caption(f"{len(memories)} stored memories")
        for mem in reversed(memories):
            is_new = mem["id"] in st.session_state.new_ids
            badge = '<span class="badge-new">NEW</span>' if is_new else ""
            mem_type = mem.get("type", "fact")
            content = mem.get("content", "")
            imp = mem.get("importance", 0)
            date = mem.get("created_at", "")[:10]
            st.markdown(
                f"""<div class="mem-card">
<div class="mem-tag-row">
    <span class="mem-tag">{mem_type}</span>
    {badge}
</div>
<div class="mem-text">{content}</div>
<div class="mem-meta">confidence {imp:.0%} &middot; {date}</div>
</div>""",
                unsafe_allow_html=True,
            )

    st.markdown(
        """
    <div class="sidebar-disclaimer">
      RecallFabric &middot; Local Memory AI<br>
      PostgreSQL &middot; FastEmbed &middot; Ollama
    </div>
    """,
        unsafe_allow_html=True,
    )


st.markdown(
    """
<div class="rf-header">
  <div class="rf-brand">
    <div class="rf-avatar">🧠</div>
    <div>
      <div class="rf-title">RecallFabric</div>
      <div class="rf-subtitle">Powered by qwen2.5 &middot; Continuous Memory Architecture</div>
    </div>
  </div>
  <div class="rf-badge">Memory Active</div>
</div>
""",
    unsafe_allow_html=True,
)

tab_chat, tab_memories, tab_keys = st.tabs(["💬 Chat", "🧠 Memories", "🔑 API Keys & Account"])

with tab_chat:
    for msg in st.session_state.messages:
        if msg["role"] == "user":
            render_user_message(msg["content"])
        else:
            render_assistant_message(msg["content"], msg.get("retrieved"))

    if not st.session_state.messages:
        with st.chat_message("assistant"):
            st.markdown(
                "Hi! I'm your AI assistant with persistent memory. "
                "Tell me things about yourself and I'll remember them across conversations. "
                "Watch the **sidebar** update live as I learn about you."
            )

    prompt = st.chat_input("Message RecallFabric...")
    if prompt:
        st.session_state.messages.append({"role": "user", "content": prompt})
        render_user_message(prompt)

        with st.chat_message("assistant"):
            ph = st.empty()
            ph.markdown('<span class="thinking">Thinking...</span>', unsafe_allow_html=True)
            history = [
                {"role": m["role"], "content": m["content"]} for m in st.session_state.messages[:-1]
            ]
            reply, retrieved_items, new_mems = chat_with_service(
                API_URL, USER_ID, prompt, history, extract=True
            )
            ph.empty()

            st.markdown(reply)
            if retrieved_items:
                with st.expander("🧠 Memory context used"):
                    for item in retrieved_items:
                        st.markdown(
                            f'<div class="ctx-box">📌 {item["content"]}</div>',
                            unsafe_allow_html=True,
                        )

        st.session_state.messages.append(
            {
                "role": "assistant",
                "content": reply,
                "retrieved": retrieved_items,
            }
        )

        try:
            st.session_state.memories = fetch_memories(API_URL, USER_ID, limit=50)
        except Exception:
            pass
        st.session_state.new_ids = {m["id"] for m in new_mems}
        st.rerun()

with tab_memories:
    with st.expander("➕ Create New Memory", expanded=False):
        with st.form("create_memory_form", clear_on_submit=True):
            new_content = st.text_area("Content", placeholder="e.g. User prefers espresso")
            col_t1, col_t2 = st.columns(2)
            with col_t1:
                new_type = st.selectbox(
                    "Type",
                    ["preference", "fact", "goal", "skill", "profile", "other"],
                )
                new_imp = st.slider("Importance", 0.0, 1.0, 0.7, 0.05)
            with col_t2:
                new_src = st.text_input("Source", value="dashboard")
                new_conf = st.slider("Confidence", 0.0, 1.0, 1.0, 0.05)
            new_reason = st.text_input("Creation Reason (optional)")
            new_dedupe = st.checkbox("Deduplicate / Consolidate against existing", value=False)
            create_submitted = st.form_submit_button("Create Memory")
            if create_submitted and new_content.strip():
                try:
                    res = create_memory(
                        api_url=API_URL,
                        user_id=USER_ID,
                        content=new_content.strip(),
                        memory_type=new_type,
                        importance=new_imp,
                        confidence=new_conf,
                        source=new_src,
                        creation_reason=new_reason.strip() or None,
                        deduplicate=new_dedupe,
                    )
                    st.success(f"Memory created (v{res['version']})!")
                    st.session_state.memories = fetch_memories(API_URL, USER_ID, limit=50)
                    st.rerun()
                except DashboardClientError as exc:
                    st.error(f"Creation failed: {exc.detail}")

    st.subheader("🔍 Search Memories")
    col_s1, col_s2 = st.columns([3, 1])
    with col_s1:
        search_query = st.text_input(
            "Search query",
            placeholder="Search your memories...",
            label_visibility="collapsed",
        )
    with col_s2:
        plain_text_toggle = st.toggle("Plain-text search", value=False)

    if search_query.strip():
        if plain_text_toggle:
            st.caption("Using plain-text substring search (/memories/search)")
            try:
                search_results = search_memories(
                    api_url=API_URL,
                    user_id=USER_ID,
                    query=search_query.strip(),
                )
                if not search_results:
                    st.info("No matching memories found.")
                else:
                    for sm in search_results:
                        st.markdown(
                            f"**[{sm['type']}]** {sm['content']} "
                            f"`v{sm['version']}` &middot; {sm['status']}"
                        )
            except DashboardClientError as exc:
                st.error(f"Search failed: {exc.detail}")
        else:
            st.caption("Using semantic retrieval with scoring (/memories/retrieve)")
            try:
                retrieved_results = retrieve_memories(
                    api_url=API_URL,
                    user_id=USER_ID,
                    query=search_query.strip(),
                    track_access=True,
                )
                if not retrieved_results:
                    st.info("No memories met retrieval threshold.")
                else:
                    for rm in retrieved_results:
                        sc = rm.get("score", 0.0)
                        bd = rm.get("score_breakdown", {})
                        st.markdown(f"**[{rm['type']}]** {rm['content']} (Score: `{sc:.3f}`)")
                        if bd:
                            st.caption(
                                f"Relevance: {bd.get('relevance', 0):.2f} | "
                                f"Importance: {bd.get('importance', 0):.2f} | "
                                f"Confidence: {bd.get('confidence', 0):.2f} | "
                                f"Recency: {bd.get('recency', 0):.2f} | "
                                f"Frequency: {bd.get('frequency', 0):.2f}"
                            )
            except DashboardClientError as exc:
                st.error(f"Retrieval failed: {exc.detail}")

    st.markdown("---")

    st.subheader("📋 Memory Catalog")
    col_f1, col_f2, col_f3 = st.columns([2, 2, 2])
    with col_f1:
        filter_type = st.selectbox(
            "Filter Type",
            ["All", "preference", "fact", "goal", "skill", "profile", "other"],
        )
    with col_f2:
        filter_status = st.selectbox("Filter Status", ["All", "active", "disabled"])
    with col_f3:
        page_size = st.selectbox("Page Size", [10, 20, 50], index=0)

    try:
        active_type = None if filter_type == "All" else filter_type
        active_status = None if filter_status == "All" else filter_status
        catalog_memories = fetch_memories(
            api_url=API_URL,
            user_id=USER_ID,
            limit=page_size,
            offset=st.session_state.memories_page * page_size,
            memory_type=active_type,
            status=active_status,
        )
    except Exception as exc:
        catalog_memories = []
        st.error(f"Failed to fetch memories: {exc}")

    if catalog_memories:
        table_rows = []
        for m in catalog_memories:
            table_rows.append(
                {
                    "Content": m.get("content", ""),
                    "Type": m.get("type", ""),
                    "Importance": f"{m.get('importance', 0):.2f}",
                    "Confidence": f"{m.get('confidence', 0):.2f}",
                    "Status": m.get("status", ""),
                    "Version": m.get("version", 1),
                    "Updated": str(m.get("updated_at", ""))[:19],
                    "ID": m.get("id", ""),
                }
            )
        st.dataframe(table_rows, use_container_width=True)

        col_p1, col_p2, col_p3 = st.columns([1, 2, 1])
        with col_p1:
            if st.button("◀ Previous", disabled=st.session_state.memories_page <= 0):
                st.session_state.memories_page -= 1
                st.rerun()
        with col_p2:
            st.markdown(
                f"<div style='text-align:center;'>Page {st.session_state.memories_page + 1}</div>",
                unsafe_allow_html=True,
            )
        with col_p3:
            if st.button("Next ▶", disabled=len(catalog_memories) < page_size):
                st.session_state.memories_page += 1
                st.rerun()

        st.markdown("### Manage Selected Memory")
        sel_idx = st.selectbox(
            "Select Memory to inspect or modify",
            range(len(catalog_memories)),
            format_func=lambda i: (
                f"v{catalog_memories[i]['version']} "
                f"[{catalog_memories[i]['status']}] "
                f"{catalog_memories[i]['content'][:60]}... "
                f"({catalog_memories[i]['id'][:8]})"
            ),
        )
        cur_mem = catalog_memories[sel_idx]
        mid = cur_mem["id"]
        mver = cur_mem["version"]

        col_m1, col_m2 = st.columns(2)
        with col_m1:
            if cur_mem["status"] == "active":
                if st.button("🚫 Disable Memory", key=f"dis_{mid}", use_container_width=True):
                    try:
                        disable_memory(API_URL, USER_ID, mid)
                        st.success("Memory disabled.")
                        st.session_state.memories = fetch_memories(API_URL, USER_ID)
                        st.rerun()
                    except DashboardClientError as exc:
                        st.error(f"Disable failed: {exc.detail}")
            else:
                if st.button("✅ Enable Memory", key=f"ena_{mid}", use_container_width=True):
                    try:
                        enable_memory(API_URL, USER_ID, mid)
                        st.success("Memory re-enabled.")
                        st.session_state.memories = fetch_memories(API_URL, USER_ID)
                        st.rerun()
                    except DashboardClientError as exc:
                        st.error(f"Enable failed: {exc.detail}")

        with col_m2:
            del_confirm = st.checkbox("Confirm permanent deletion", key=f"del_chk_{mid}")
            if st.button(
                "🗑️ Delete Memory",
                key=f"del_{mid}",
                disabled=not del_confirm,
                use_container_width=True,
            ):
                try:
                    delete_memory(API_URL, USER_ID, mid)
                    st.success("Memory deleted.")
                    st.session_state.memories = fetch_memories(API_URL, USER_ID)
                    st.rerun()
                except DashboardClientError as exc:
                    st.error(f"Delete failed: {exc.detail}")

        with st.expander("✏️ Edit Memory Content / Attributes"):
            with st.form(f"edit_form_{mid}"):
                edit_content = st.text_area("Content", value=cur_mem.get("content", ""))
                c_e1, c_e2 = st.columns(2)
                type_opts = ["preference", "fact", "goal", "skill", "profile", "other"]
                cur_t = cur_mem.get("type", "fact")
                t_idx = type_opts.index(cur_t) if cur_t in type_opts else 0
                with c_e1:
                    edit_type = st.selectbox("Type", type_opts, index=t_idx)
                    edit_imp = st.slider(
                        "Importance", 0.0, 1.0, float(cur_mem.get("importance", 0.5)), 0.05
                    )
                with c_e2:
                    edit_conf = st.slider(
                        "Confidence", 0.0, 1.0, float(cur_mem.get("confidence", 1.0)), 0.05
                    )
                    status_opts = ["active", "disabled"]
                    cur_s = cur_mem.get("status", "active")
                    s_idx = status_opts.index(cur_s) if cur_s in status_opts else 0
                    edit_status = st.selectbox("Status", status_opts, index=s_idx)
                edit_src = st.text_input("Source", value=cur_mem.get("source", "dashboard"))
                edit_reason = st.text_input(
                    "Creation Reason", value=cur_mem.get("creation_reason") or ""
                )

                if st.form_submit_button("💾 Save Changes"):
                    try:
                        up_res = update_memory(
                            api_url=API_URL,
                            user_id=USER_ID,
                            memory_id=mid,
                            expected_version=mver,
                            content=edit_content,
                            memory_type=edit_type,
                            importance=edit_imp,
                            confidence=edit_conf,
                            source=edit_src,
                            creation_reason=edit_reason.strip() or None,
                            status=edit_status,
                        )
                        st.success(f"Updated memory to v{up_res['version']}!")
                        st.session_state.memories = fetch_memories(API_URL, USER_ID)
                        st.rerun()
                    except DashboardClientError as exc:
                        if exc.status_code == 409:
                            st.warning(
                                "⚠️ Version conflict (409): memory was changed. "
                                "Reloading latest version..."
                            )
                            try:
                                get_memory(API_URL, USER_ID, mid)
                                st.session_state.memories = fetch_memories(API_URL, USER_ID)
                                st.rerun()
                            except Exception as e:
                                st.error(f"Reload failed: {e}")
                        else:
                            st.error(f"Update failed: {exc.detail}")

        with st.expander("📜 Version History (/versions)"):
            try:
                hist_items = get_memory_history(API_URL, USER_ID, mid)
                if not hist_items:
                    st.info("No prior versions.")
                else:
                    for h in hist_items:
                        st.markdown(
                            f"**v{h['version']}** ({h['status']}) &middot; "
                            f"{h.get('updated_at', '')[:19]}<br>"
                            f"*{h['content']}*<br>"
                            f"<small>Reason: {h.get('creation_reason')} | "
                            f"Source: {h.get('source')}</small>",
                            unsafe_allow_html=True,
                        )
                        st.markdown("---")
            except DashboardClientError as exc:
                st.error(f"Failed to fetch history: {exc.detail}")

        with st.expander("🔍 Provenance Feed (/provenance)"):
            try:
                prov_items = get_memory_provenance(API_URL, USER_ID, mid)
                if not prov_items:
                    st.info("No provenance events recorded.")
                else:
                    for ev in prov_items:
                        st.markdown(
                            f"**{ev['event_type'].upper()}** &middot; "
                            f"rev v{ev.get('memory_version')} &middot; "
                            f"{str(ev.get('created_at', ''))[:19]}<br>"
                            f"Actor: `{ev.get('actor')}` | Reason: {ev.get('reason')}<br>"
                            f"<small>Detail: {ev.get('detail')}</small>",
                            unsafe_allow_html=True,
                        )
                        st.markdown("---")
            except DashboardClientError as exc:
                st.error(f"Failed to fetch provenance: {exc.detail}")
    else:
        st.info("No memories found matching current filter.")

    st.markdown("---")

    st.subheader("🔬 Extraction Preview Panel")
    st.caption("Preview candidate memories extracted by LLM without saving (dry_run=true).")
    preview_text = st.text_area(
        "Sample text to extract from",
        height=90,
        placeholder="I work at Acme Corp. I prefer dark roast coffee and I want to learn Rust.",
    )
    if st.button("Preview Extraction"):
        if preview_text.strip():
            with st.spinner("Extracting candidates..."):
                try:
                    p_res = preview_extraction(API_URL, USER_ID, preview_text.strip())
                    candidates = p_res.get("candidates", [])
                    rejected = p_res.get("rejected", [])
                    st.markdown(f"**Found {len(candidates)} candidate(s)**")
                    for c in candidates:
                        st.markdown(
                            f"✅ **[{c.get('type', 'fact')}]** {c.get('content')} "
                            f"(Imp: `{c.get('importance')}`, Conf: `{c.get('confidence')}`)"
                        )
                    if rejected:
                        st.markdown(f"**Rejected {len(rejected)} candidate(s)**")
                        for r in rejected:
                            st.markdown(
                                f"❌ *{r.get('content')}* &mdash; **Reason**: `{r.get('reason')}`"
                            )
                except DashboardClientError as exc:
                    st.error(f"Extraction preview failed: {exc.detail}")
        else:
            st.warning("Please enter some text to preview extraction.")

with tab_keys:
    st.subheader("🔑 API Key Management & User Onboarding")
    st.caption("Generate scoped API keys, inspect usage, or manage user data export and deletion.")

    c_acc1, c_acc2 = st.columns(2)
    with c_acc1:
        st.markdown("#### Issue New API Key")
        with st.form("signup_key_form"):
            new_uid = st.text_input("User ID", value=USER_ID)
            key_name = st.text_input("Key Description / Name", value="development-key")
            admin_tok = st.text_input(
                "Admin Token (optional)",
                type="password",
                help="Required if self-serve signup is disabled",
            )
            submit_key = st.form_submit_button("Generate API Key")
            if submit_key:
                if not new_uid.strip():
                    st.error("User ID is required.")
                else:
                    try:
                        if admin_tok.strip():
                            res = create_api_key(
                                API_URL,
                                new_uid.strip(),
                                name=key_name.strip() or "default",
                                admin_token=admin_tok.strip(),
                            )
                            st.success(f"Key created successfully for {new_uid}!")
                            st.code(res.get("key"), language="text")
                            st.warning("Save this key now. It cannot be shown again.")
                        else:
                            res = signup_user(
                                API_URL,
                                new_uid.strip(),
                                name=key_name.strip() or "default",
                            )
                            st.success(f"User onboarded! Key generated for {new_uid}:")
                            st.code(res.get("api_key"), language="text")
                            st.warning("Save this key now. It cannot be shown again.")
                    except DashboardClientError as exc:
                        st.error(f"Failed to issue key: {exc.detail}")

    with c_acc2:
        st.markdown("#### User Memory & Usage Summary")
        user_mems = st.session_state.memories
        total_mems = len(user_mems)
        active_count = sum(1 for m in user_mems if m.get("status") == "active")
        types_breakdown: dict[str, int] = {}
        for m in user_mems:
            t = m.get("type", "fact")
            types_breakdown[t] = types_breakdown.get(t, 0) + 1

        st.metric("Total Memories", total_mems)
        col_st1, col_st2 = st.columns(2)
        with col_st1:
            st.metric("Active", active_count)
        with col_st2:
            st.metric("Disabled", total_mems - active_count)

        if types_breakdown:
            st.markdown("**Types Breakdown:**")
            for t_name, t_cnt in sorted(types_breakdown.items()):
                st.markdown(f"- `{t_name}`: {t_cnt}")

    st.markdown("---")
    st.markdown("#### Manage Existing API Keys")
    admin_auth = st.text_input(
        "Enter Admin Token to inspect or revoke keys",
        type="password",
        key="admin_list_tok",
    )
    if st.button("List Keys"):
        if not admin_auth.strip():
            st.warning("Admin Token is required to list existing keys.")
        else:
            try:
                keys = list_api_keys(API_URL, admin_token=admin_auth.strip(), user_id=USER_ID)
                if not keys:
                    st.info(f"No active API keys found for user '{USER_ID}'.")
                else:
                    for k in keys:
                        c_k1, c_k2, c_k3 = st.columns([3, 2, 1])
                        with c_k1:
                            st.markdown(f"**{k.get('name')}** (`{k.get('id')[:8]}...`)")
                            st.caption(f"Created: {str(k.get('created_at', ''))[:19]}")
                        with c_k2:
                            st.markdown(
                                f"Status: {'Active' if not k.get('revoked_at') else 'Revoked'}"
                            )
                        with c_k3:
                            if not k.get("revoked_at"):
                                if st.button("Revoke", key=f"rev_{k.get('id')}"):
                                    revoke_api_key(
                                        API_URL, k.get("id"), admin_token=admin_auth.strip()
                                    )
                                    st.success("Key revoked.")
                                    st.rerun()
            except DashboardClientError as exc:
                st.error(f"Failed to list keys: {exc.detail}")

    st.markdown("---")
    st.markdown("#### Data Portability & GDPR Controls")
    c_p1, c_p2 = st.columns(2)
    with c_p1:
        st.markdown("**Export All Memories & Events (JSON)**")
        st.caption("Download a complete machine-readable archive of all memories and provenance.")
        if st.button("Fetch Export Archive"):
            try:
                export_data = export_user_data(API_URL, USER_ID, API_KEY)
                export_json = json.dumps(export_data, indent=2)
                st.download_button(
                    label="⬇️ Download Export JSON",
                    data=export_json,
                    file_name=f"recallfabric_{USER_ID}_export.json",
                    mime="application/json",
                )
            except DashboardClientError as exc:
                st.error(f"Export failed: {exc.detail}")

    with c_p2:
        st.markdown("**Purge All Memories (Right to be Forgotten)**")
        st.caption("Permanently delete all memories, embeddings, and provenance records.")
        confirm_purge = st.checkbox("I confirm permanent deletion of all my memories")
        if st.button("🗑️ Delete All My Memories", disabled=not confirm_purge):
            try:
                res = delete_all_user_memories(API_URL, USER_ID, API_KEY)
                st.success(f"Purged {res.get('deleted_memories', 0)} memories successfully.")
                st.session_state.memories = []
                st.session_state.messages = []
                st.rerun()
            except DashboardClientError as exc:
                st.error(f"Purge failed: {exc.detail}")
