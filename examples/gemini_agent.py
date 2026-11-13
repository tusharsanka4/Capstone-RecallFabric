"""Example: Google Gemini agent with vs without RecallFabric memory.

Shows how cross-session preferences are forgotten in naive chat completions,
and how `with_memory` automatically recalls and injects them into Gemini system instructions.
"""

import os

from recallfabric_client import RecallFabric, with_memory

USER_ID = "chen_data_engineer"
RECALLFABRIC_URL = os.getenv("RECALLFABRIC_BASE_URL", "http://localhost:8000")


def get_gemini_runner():
    """Returns a Google GenAI runner, or a mock if GEMINI_API_KEY is unset."""
    api_key = os.getenv("GEMINI_API_KEY")
    if api_key:
        import google.generativeai as genai

        genai.configure(api_key=api_key)

        def runner(messages):
            system_msg = next((m["content"] for m in messages if m["role"] == "system"), "")
            user_msg = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
            model = genai.GenerativeModel(
                model_name="gemini-1.5-flash",
                system_instruction=system_msg if system_msg else None,
            )
            res = model.generate_content(user_msg)
            return res.text

        return runner

    def mock_runner(messages):
        system_content = next((m["content"] for m in messages if m["role"] == "system"), "")
        user_content = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
        if "DuckDB" in system_content or "Polars" in system_content:
            return (
                f"[With RecallFabric Memory Detected]\n"
                f"Using DuckDB and Polars for pipeline processing according to user preferences.\n"
                f"Processed request: '{user_content}'"
            )
        return (
            f"[Without Memory - Naive Gemini]\n"
            f"Here is a generic Pandas pipeline reading a CSV into a pandas.DataFrame...\n"
            f"Processed request: '{user_content}'"
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
    print("DEMO: Google Gemini Agent With vs Without RecallFabric Memory")
    print("=" * 70)

    llm = get_gemini_runner()
    rf = get_client()

    # 1. Setup: Explicitly remember user technical preferences
    print("\n[Step 1] Storing user data stack preferences into RecallFabric...")
    rf.remember(
        "User prefers Polars and DuckDB for data processing pipelines rather than Pandas",
        type="preference",
        importance=0.9,
    )
    print("-> Memory stored successfully.")

    # 2. Naive Agent without RecallFabric
    print("\n[Step 2] Session 2: Naive Agent WITHOUT Memory:")
    naive_messages = [{"role": "user", "content": "How do I aggregate 10GB of telemetry logs?"}]
    naive_reply = llm(naive_messages)
    print(f"Gemini Response:\n{naive_reply}\n")

    # 3. Agent WITH RecallFabric memory wrapper
    print("\n[Step 3] Session 2: Agent WITH RecallFabric Memory (with_memory):")
    smart_agent = with_memory(llm, rf, user_id=USER_ID)
    smart_reply = smart_agent(naive_messages)
    print(f"Gemini Response:\n{smart_reply}\n")

    print("=" * 70)
    print("Summary: RecallFabric augmented the Gemini request with stored stack context.")
    print("=" * 70)


if __name__ == "__main__":
    run_demo()
