# RecallFabric Python Client

The official Python client SDK for [RecallFabric](https://github.com/tusharsanka4/Capstone-RecallFabric) — the persistent memory and context fabric for AI agents.

## Installation

```bash
pip install recallfabric-client
```

Or for development:

```bash
pip install -e sdk/python
```

## 5-Line Quickstart

```python
from recallfabric_client import RecallFabric

rf = RecallFabric(base_url="http://localhost:8000")
rf.remember("User prefers Python and dark mode in all editors", type="preference")

memories = rf.recall("editor preferences")
print(memories.context)
```

## Automatic Memory Wrapper (`with_memory`)

Wrap any LLM function to automatically recall context and extract new memories in the background:

```python
from recallfabric_client import RecallFabric, with_memory

rf = RecallFabric()


def chat_model(messages):
    # Call your preferred LLM (OpenAI, Anthropic, Gemini, Ollama, etc.)
    return "Understood, I will use Python and dark mode."


agent = with_memory(chat_model, rf, user_id="user_123")
response = agent([{"role": "user", "content": "How should we build this script?"}])
```

## Features

- **Sync & Async Support**: Both `RecallFabric` and `AsyncRecallFabric` clients.
- **Resilient Operations**: Automatic exponential backoff retries on `429` and `5xx` errors.
- **Idempotency**: Prevent duplicate writes across retries with `idempotency_key`.
- **Framework Adapters**: Drop-in LangChain (`RecallFabricRetriever`, `RecallFabricMemory`) and LlamaIndex (`RecallFabricLlamaIndexRetriever`) support.
