"""Example: Anthropic Claude agent with vs without RecallFabric memory.

Shows how cross-session preferences are forgotten in naive chat completions,
and how `with_memory` automatically recalls and injects them into Claude's prompt.
"""

import os

from recallfabric_client import RecallFabric, with_memory

USER_ID = "sarah_researcher"
RECALLFABRIC_URL = os.getenv("RECALLFABRIC_BASE_URL", "http://localhost:8000")


def get_claude_runner():
    """Returns an Anthropic Messages runner, or a mock if ANTHROPIC_API_KEY is unset."""
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if api_key:
        import anthropic

        client = anthropic.Anthropic(api_key=api_key)

        def runner(messages):
            system_msg = next((m["content"] for m in messages if m["role"] == "system"), None)
            user_msgs = [m for m in messages if m["role"] != "system"]
            kwargs = {
                "model": "claude-3-5-haiku-20241022",
                "max_tokens": 500,
                "messages": user_msgs,
            }
            if system_msg:
                kwargs["system"] = system_msg

            res = client.messages.create(**kwargs)
            return res.content[0].text

        return runner

    def mock_runner(messages):
        system_content = next((m["content"] for m in messages if m["role"] == "system"), "")
        user_content = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
        if "concise" in system_content or "bullet points" in system_content:
            return (
                f"[With RecallFabric Memory Detected]\n"
                f"- Bullet 1: Focused findings\n"
                f"- Bullet 2: Concise summary without preamble (per user preferences)\n"
                f"Query answered: '{user_content}'"
            )
        return (
            f"[Without Memory - Naive Claude]\n"
            f"Greetings! Certainly, I would be delighted to elaborate in comprehensive detail "
            f"across multiple long paragraphs regarding your question: '{user_content}'..."
        )

    return mock_runner


def get_client():
    """Return a RecallFabric client connected to localhost:8000, or in-process app if offline."""
    try:
        client = RecallFabric(
            base_url=RECALLFABRIC_URL, user_id=USER_ID, timeout=1.5, max_retries=0
        )
        client.capabilities()
        print(f"[Connected to live RecallFabric service at {RECALLFABRIC_URL}]")
        return client
    except Exception:
        from fastapi.testclient import TestClient

        from recallfabric.core.config import Settings
        from recallfabric.main import create_app

        print("[Notice: Live service offline; running against in-process RecallFabric engine]")
        app = create_app(Settings(environment="development", auth_enabled=False))
        tc = TestClient(app, base_url="http://testserver")
        tc.__enter__()
        return RecallFabric(base_url="http://testserver", http_client=tc, user_id=USER_ID)


def run_demo():
    print("=" * 70)
    print("DEMO: Anthropic Claude Agent With vs Without RecallFabric Memory")
    print("=" * 70)

    llm = get_claude_runner()
    rf = get_client()

    # 1. Setup: Explicitly remember user technical preferences
    print("\n[Step 1] Storing user communication preferences into RecallFabric...")
    rf.remember(
        "User prefers concise bullet points and strictly no conversational filler or preambles",
        type="preference",
        importance=0.9,
    )
    print("-> Memory stored successfully.")

    # 2. Naive Agent without RecallFabric
    print("\n[Step 2] Session 2: Naive Agent WITHOUT Memory:")
    naive_messages = [
        {"role": "user", "content": "Explain the architectural tradeoffs of microservices."}
    ]
    naive_reply = llm(naive_messages)
    print(f"Claude Response:\n{naive_reply}\n")

    # 3. Agent WITH RecallFabric memory wrapper
    print("\n[Step 3] Session 2: Agent WITH RecallFabric Memory (with_memory):")
    smart_agent = with_memory(llm, rf, user_id=USER_ID)
    smart_reply = smart_agent(naive_messages)
    print(f"Claude Response:\n{smart_reply}\n")

    print("=" * 70)
    print("Summary: RecallFabric seamlessly injected user style guidelines into system context.")
    print("=" * 70)


if __name__ == "__main__":
    run_demo()
