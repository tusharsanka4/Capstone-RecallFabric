"""Example: OpenAI agent with vs without RecallFabric memory.

Shows how cross-session preferences are forgotten in naive chat completions,
and how `with_memory` automatically recalls and injects them seamlessly.
"""

import os

from recallfabric_client import RecallFabric, with_memory

USER_ID = "alex_dev_42"
RECALLFABRIC_URL = os.getenv("RECALLFABRIC_BASE_URL", "http://localhost:8000")


def get_llm_runner():
    """Returns an OpenAI completion function, or a mock if OPENAI_API_KEY is unset."""
    api_key = os.getenv("OPENAI_API_KEY")
    if api_key:
        from openai import OpenAI

        client = OpenAI(api_key=api_key)

        def runner(messages):
            res = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=messages,
                temperature=0.0,
            )
            return res.choices[0].message.content

        return runner

    # Mock runner demonstrating the difference
    def mock_runner(messages):
        system_content = next((m["content"] for m in messages if m["role"] == "system"), "")
        user_content = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
        if "pytest" in system_content or "async" in system_content:
            return (
                f"[With RecallFabric Memory Detected]\n"
                f"Generating async FastAPI test suite using pytest as per your saved preferences.\n"
                f"Prompt query: '{user_content}'"
            )
        return (
            f"[Without Memory - Naive LLM]\n"
            f"Here is a generic unittest synchronous example using 4 spaces.\n"
            f"Prompt query: '{user_content}'"
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
    print("DEMO: OpenAI Agent With vs Without RecallFabric Memory")
    print("=" * 70)

    llm = get_llm_runner()
    rf = get_client()

    # 1. Setup: Explicitly remember user technical preferences
    print("\n[Step 1] Storing user preferences into RecallFabric...")
    rf.remember(
        "User prefers async Python with pytest and FastAPI, using tabs for indentation",
        type="preference",
        importance=0.95,
    )
    print("-> Memory stored successfully.")

    # 2. Naive Agent without RecallFabric
    print("\n[Step 2] Session 2: Naive Agent WITHOUT Memory:")
    naive_messages = [{"role": "user", "content": "How should I structure my backend unit tests?"}]
    naive_reply = llm(naive_messages)
    print(f"Agent Response:\n{naive_reply}\n")

    # 3. Agent WITH RecallFabric memory wrapper
    print("\n[Step 3] Session 2: Agent WITH RecallFabric Memory (with_memory):")
    smart_agent = with_memory(llm, rf, user_id=USER_ID)
    smart_reply = smart_agent(naive_messages)
    print(f"Agent Response:\n{smart_reply}\n")

    print("=" * 70)
    print("Summary: with_memory automatically fetched user preferences and injected")
    print("them into context without any manual prompt engineering!")
    print("=" * 70)


if __name__ == "__main__":
    run_demo()
