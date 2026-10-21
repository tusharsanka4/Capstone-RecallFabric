"""RecallFabric - Claude-inspired dark mode chatbot with live memory sidebar."""

import html
import streamlit as st
import httpx
from openai import OpenAI

API_URL    = "http://127.0.0.1:8000"
OLLAMA_URL = "http://127.0.0.1:11434/v1"
MODEL      = "qwen2.5:0.5b"
USER_ID    = "demo_user"

llm = OpenAI(base_url=OLLAMA_URL, api_key="ollama")

st.set_page_config(
    page_title="RecallFabric",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
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
    max-width: 820px !important;
    padding-top: 2rem !important;
    padding-bottom: 7rem !important;
    padding-left: 2rem !important;
    padding-right: 2rem !important;
    margin: 0 auto;
    background: transparent !important;
}

/* ── Header: Claude Minimal Dark Style ── */
.rf-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 2rem;
    padding-bottom: 1.2rem;
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
""", unsafe_allow_html=True)


# ── Helpers ──────────────────────────────────────────────────────────────────
def fetch_memories():
    try:
        r = httpx.get(f"{API_URL}/memories", params={"user_id": USER_ID, "limit": 50}, timeout=5.0)
        if r.status_code == 200:
            return r.json().get("items", [])
    except Exception:
        pass
    return []


def extract_memories(text):
    try:
        r = httpx.post(
            f"{API_URL}/extraction",
            json={"user_id": USER_ID, "text": text, "source": "chat_demo"},
            timeout=60.0,
        )
        if r.status_code == 201:
            return r.json().get("extracted", [])
    except Exception:
        pass
    return []


def retrieve_context(query):
    try:
        r = httpx.post(
            f"{API_URL}/memories/retrieve",
            json={"user_id": USER_ID, "query": query, "limit": 8},
            timeout=10.0,
        )
        if r.status_code == 200:
            items = r.json().get("items", [])
            good_items = [i for i in items if i.get("importance", 0) >= 0.5]
            final_items = good_items if good_items else items
            if final_items:
                ctx = "\n".join(f"- {i['content']}" for i in final_items)
                return ctx, final_items
    except Exception:
        pass
    return "", []


def chat_with_llm(user_text, context):
    sys_content = (
        "You are RecallFabric, a helpful, friendly AI assistant with persistent memory. "
        "The user is a human speaking with you. You are the AI.\n\n"
        "Rules:\n"
        "- When the user tells you something (like a preference, hobby, or greeting), respond conversationally, warmly, and relevantly to what they just said.\n"
        "- When the user asks what you remember about them or asks questions about their background/details, answer directly using the Memory Notes below.\n"
        "- Address the user as 'You' and yourself as 'I'. Keep responses concise, direct, and natural without repetitive phrases."
    )

    try:
        history = [
            {"role": m["role"], "content": m["content"]}
            for m in st.session_state.messages[-6:]
        ]

        if context:
            sys_content += f"\n\nMemory Notes about the User:\n{context}\n\nUse these notes when the user asks about their background."

        messages = [{"role": "system", "content": sys_content}] + history
        messages.append({"role": "user", "content": user_text})

        resp = llm.chat.completions.create(
            model=MODEL,
            messages=messages,
            temperature=0.4,
            max_tokens=250,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        return f"Error: {e}"


def clear_all_memories():
    deleted = 0
    try:
        mems = fetch_memories()
        for m in mems:
            r = httpx.delete(
                f"{API_URL}/memories/{m['id']}",
                params={"user_id": USER_ID},
                timeout=5.0,
            )
            if r.status_code == 204:
                deleted += 1
    except Exception as e:
        return False, str(e)
    return True, deleted


def check_status():
    api_ok, ollama_ok = False, False
    try:
        api_ok = httpx.get(f"{API_URL}/health", timeout=2).status_code == 200
    except Exception:
        pass
    try:
        ollama_ok = httpx.get("http://127.0.0.1:11434/api/tags", timeout=2).status_code == 200
    except Exception:
        pass
    return api_ok, ollama_ok


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


# ── Session state ──────────────────────────────────────────────────────────────
if "messages" not in st.session_state:
    st.session_state.messages = []
if "memories" not in st.session_state:
    st.session_state.memories = fetch_memories()
if "new_ids" not in st.session_state:
    st.session_state.new_ids = set()


# ── Sidebar ────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("""
    <div class="sb-header">
        <span class="sb-title">🧠 Memory Stream</span>
        <span class="sb-user-pill">demo_user</span>
    </div>
    """, unsafe_allow_html=True)

    api_ok, ollama_ok = check_status()
    a = '<span class="dot-ok">●</span> API'    if api_ok    else '<span class="dot-fail">○</span> API'
    o = '<span class="dot-ok">●</span> Ollama' if ollama_ok else '<span class="dot-fail">○</span> Ollama'
    st.markdown(f"""
    <div class="status-bar">
        <span class="status-pill">{a}</span>
        <span class="status-pill">{o}</span>
    </div>
    """, unsafe_allow_html=True)

    c1, c2 = st.columns(2)
    with c1:
        if st.button("↻ Refresh", use_container_width=True):
            st.session_state.memories = fetch_memories()
            st.session_state.new_ids = set()
            st.rerun()
    with c2:
        if st.button("✕ Clear", use_container_width=True):
            ok, result = clear_all_memories()
            if ok:
                st.session_state.memories = []
                st.session_state.new_ids = set()
                st.rerun()
            else:
                st.error(str(result))

    st.markdown("---")

    memories = st.session_state.memories
    if not memories:
        st.caption("No memories yet. Chat with the AI to teach it!")
    else:
        st.caption(f"{len(memories)} stored memories")
        for mem in reversed(memories):
            is_new   = mem["id"] in st.session_state.new_ids
            badge    = '<span class="badge-new">NEW</span>' if is_new else ""
            mem_type = mem.get("type", "fact")
            content  = mem.get("content", "")
            imp      = mem.get("importance", 0)
            date     = mem.get("created_at", "")[:10]
            st.markdown(f"""<div class="mem-card">
<div class="mem-tag-row">
    <span class="mem-tag">{mem_type}</span>
    {badge}
</div>
<div class="mem-text">{content}</div>
<div class="mem-meta">confidence {imp:.0%} &middot; {date}</div>
</div>""", unsafe_allow_html=True)

    st.markdown("""
    <div class="sidebar-disclaimer">
      RecallFabric &middot; Local Memory AI<br>
      PostgreSQL &middot; FastEmbed &middot; Ollama
    </div>
    """, unsafe_allow_html=True)


# ── Main Area ──────────────────────────────────────────────────────────────────
st.markdown("""
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
""", unsafe_allow_html=True)

# Render history
for msg in st.session_state.messages:
    if msg["role"] == "user":
        render_user_message(msg["content"])
    else:
        render_assistant_message(msg["content"], msg.get("retrieved"))

# Welcome state
if not st.session_state.messages:
    with st.chat_message("assistant"):
        st.markdown(
            "Hi! I'm your AI assistant with persistent memory. "
            "Tell me things about yourself and I'll remember them across conversations. "
            "Watch the **sidebar** update live as I learn about you."
        )

# ── Chat input ─────────────────────────────────────────────────────────────────
prompt = st.chat_input("Message RecallFabric...")

if prompt:
    st.session_state.messages.append({"role": "user", "content": prompt})
    render_user_message(prompt)

    with st.chat_message("assistant"):
        ph = st.empty()

        # Step 1: Retrieve prior memory context before adding current turn
        ph.markdown('<span class="thinking">Searching memory...</span>', unsafe_allow_html=True)
        context, retrieved_items = retrieve_context(prompt)

        # Step 2: Generate response using prior memory
        ph.markdown('<span class="thinking">Thinking...</span>', unsafe_allow_html=True)
        reply = chat_with_llm(prompt, context)
        ph.empty()

        st.markdown(reply)
        if retrieved_items:
            with st.expander("🧠 Memory context used"):
                for item in retrieved_items:
                    st.markdown(
                        f'<div class="ctx-box">📌 {item["content"]}</div>',
                        unsafe_allow_html=True,
                    )

        # Step 3: Extract & store new facts from this turn for future turns
        new_mems = extract_memories(prompt)

    st.session_state.messages.append({
        "role": "assistant",
        "content": reply,
        "retrieved": retrieved_items,
    })

    # Step 4: Update sidebar with new memories
    st.session_state.memories = fetch_memories()
    st.session_state.new_ids = {m["id"] for m in new_mems}

    st.rerun()
