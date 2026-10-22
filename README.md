# 🧠 RecallFabric

> **Persistent, structured, portable memory infrastructure for AI applications and agents.**

RecallFabric decouples long-term memory from proprietary model silos. Whether an agent runs in **Claude Desktop**, **Cursor IDE**, a **Custom GPT**, a **LangChain/LlamaIndex** pipeline, or an **OpenAI-SDK** application, RecallFabric provides a unified, cross-model memory fabric with automatic atomic fact extraction, vector semantic retrieval, deduplication, and conflict resolution.

---

## 🏗️ Architecture

```mermaid
flowchart TD
    subgraph Clients["Clients & Agent Ecosystem"]
        direction TB
        C1["MCP Agents\n(Claude Desktop, Cursor, Windsurf)"]
        C2["Client Applications\n(Python & JS SDK, LangChain, LlamaIndex)"]
        C3["OpenAI SDK Apps\n(base_url = /v1/proxy)"]
        C4["Web Chats\n(ChatGPT, Claude, Gemini via Extension)"]
        C5["External Apps\n(Webhooks / Ingest)"]
    end

    subgraph RecallFabric["RecallFabric Gateway & API Service"]
        direction TB
        M["/mcp\n(Streamable HTTP & Stdio)"]
        T["/v1/remember & /v1/recall\n(Task-Oriented AI Tools)"]
        P["/v1/proxy/chat/completions\n(OpenAI Memory Proxy)"]
        I["/v1/ingest\n(Webhook Async Extraction)"]
        D["FastAPI Engine\n(Deduplication Lock, Conflict Resolver, Multi-Factor Ranking)"]
        E["FastEmbed Pipeline\n(BAAI/bge-small-en-v1.5)"]
    end

    subgraph Database["Storage & Cloud Persistence"]
        direction TB
        PG[("PostgreSQL 16+ with pgvector\n(Neon / Supabase / Cloud SQL)")]
        AES["Field-Level Encryption\n(AES-256-GCM / Fernet)"]
    end

    subgraph LLMProviders["Extraction & Completion Providers"]
        direction TB
        L1["OpenAI\n(gpt-4o / gpt-4o-mini)"]
        L2["Anthropic\n(claude-3-5-sonnet)"]
        L3["Google Gemini\n(gemini-1.5-flash)"]
        L4["Local Ollama\n(qwen2.5 / llama3)"]
    end

    C1 -->|MCP Protocol / SSE| M
    C2 -->|REST / SDK| T
    C3 -->|OpenAI Chat Completions| P
    C4 -->|Browser Injected Recall| T
    C5 -->|Transcript Ingest| I

    M --> D
    T --> D
    P --> D
    I --> D

    D --> E
    D --> AES
    AES --> PG
    E --> PG
    D -.->|Atomic Extraction & Conflicts| LLMProviders
    P -.->|Forward Upstream (Stream Pass-through)| LLMProviders
```

---

## ⚡ 60-Second Quickstart

### (a) Connect via Model Context Protocol (MCP)

RecallFabric exposes a remote **Streamable HTTP MCP endpoint** at `/mcp` (and stdio for local environments).

Add this to your **Claude Desktop** config (`claude_desktop_config.json`) or **Cursor** (`.cursor/mcp.json`):

```json
{
  "mcpServers": {
    "recallfabric": {
      "command": "npx",
      "args": [
        "-y",
        "mcp-remote",
        "https://api.yourdomain.com/mcp",
        "--header",
        "Authorization: Bearer rf_live_your_api_key_here"
      ]
    }
  }
}
```

*Your agent instantly gains access to `remember`, `recall`, `forget`, and `memory_profile` tools.*

---

### (b) Connect via Python or JavaScript SDK

Install the official client SDK:

```bash
# Python
pip install recallfabric-client

# JavaScript / TypeScript
npm install recallfabric-client
```

Wrap any LLM call with automatic memory injection and non-blocking background learning:

```python
import openai
from recallfabric import RecallFabricClient, with_memory

client = RecallFabricClient(
    base_url="https://api.yourdomain.com",
    api_key="rf_live_your_api_key_here",
)
oai = openai.OpenAI()


# Define your completion function
def chat_completion(messages: list[dict]) -> str:
    response = oai.chat.completions.create(model="gpt-4o-mini", messages=messages)
    return response.choices[0].message.content


# Memory-augmented wrapper
smart_chat = with_memory(chat_completion, client, user_id="alice")

# Calling smart_chat automatically recalls memories, injects them into the
# system prompt, and learns new durable facts asynchronously!
reply = smart_chat([{"role": "user", "content": "I prefer dark roast espresso."}])
print(reply)
```

---

### (c) Connect via OpenAI-Compatible Memory Proxy

Point any OpenAI SDK app's `base_url` directly at the RecallFabric proxy:

```python
import openai

client = openai.OpenAI(
    base_url="https://api.yourdomain.com/v1/proxy",
    api_key="sk-your-openai-key",  # Upstream key (forwarded safely, never stored/logged)
    default_headers={"X-RecallFabric-Key": "rf_live_your_api_key_here"},
)

# Standard chat completion call - zero other code changes needed!
# RecallFabric retrieves memories, augments the system message,
# and streams the response back seamlessly.
response = client.chat.completions.create(
    model="gpt-4o-mini",
    messages=[{"role": "user", "content": "What coffee do I usually like?"}],
    stream=True,
)

for chunk in response:
    if chunk.choices[0].delta.content:
        print(chunk.choices[0].delta.content, end="", flush=True)
```

---

## 🔒 Security & Privacy Model

RecallFabric is engineered for multi-tenant isolation, enterprise security, and strict data privacy:

1. **One-Way HMAC Hashed Keys**: Plaintext API keys (`rf_...`) are never stored. The database holds only HMAC-SHA256 digests verified in constant time.
2. **Field-Level AES-256-GCM Encryption**: All memory contents are symmetrically encrypted before being written to PostgreSQL.
3. **Upstream Credential Privacy**: Headers containing upstream LLM keys (`X-Upstream-Key`, `Authorization`) are held strictly in memory during proxy forwards and **never written to logs or audit records**.
4. **SSRF Upstream Allowlist**: The proxy restricts upstream forwarding destinations to approved hosts configured in `RECALLFABRIC_PROXY_ALLOWED_UPSTREAMS`.
5. **GDPR Right-to-Portability & Deletion**:
   - `GET /v1/users/me/export`: Download complete machine-readable JSON data archive.
   - `DELETE /v1/users/me/memories`: Permanently purges all memories, embeddings, and provenance records.

*Read the complete [Security Model Specification](docs/security.md).*

---

## 📊 Evaluation & Benchmarks

RecallFabric has been benchmarked against naive vector databases and baseline zero-shot models:

- **+28% Precision @ 1** (0.64 vs 0.50) over naive vector search.
- **2.0x Conflict Resolution Accuracy** (0.84 vs 0.42) via LLM superseding.
- **66% Memory Footprint Reduction** (2.7 vs 8.0 items/conv) through deduplication.
- **100% Distractor Noise Filtering** preventing conversational bloat.
- **Sub-millisecond retrieval latency** (`0.3 ms` p50).

*Read the complete [Evaluation Summary](docs/evaluation.md) or the [Full M18 Benchmark Report](evaluation/results/REPORT.md).*

---

## ⚠️ Documented Limitations

1. **Local Vector Model Footprint**:
   The built-in FastEmbed model (`bge-small-en-v1.5`) runs locally inside the API container to deliver low latencies without API fees. This requires **~250 MB RAM**, making a 512 MB to 1 GB RAM container tier recommended.
2. **Browser Extension DOM Variance**:
   The Manifest V3 browser extension (`extensions/browser/`) monitors dynamic chat inputs across ChatGPT, Claude, and Gemini. Major upstream UI redesigns may occasionally require updated selector rules.
3. **Upstream Proxy TTFT**:
   In proxy streaming mode, time-to-first-token is dictated by upstream LLM response times. Memory recall overhead is negligible (< 10 ms).

---

## 🚀 Cloud Deployment in Under 10 Minutes

Deploy RecallFabric to your cloud provider connected to a serverless Postgres instance (Neon or Supabase):

- **Render**: One-click blueprint with [render.yaml](render.yaml)
- **Fly.io**: Global edge deployment with [fly.toml](fly.toml)
- **Railway**: Automated build and database wiring with [railway.json](railway.json)
- **Docker**: Self-host anywhere using our multi-stage [Dockerfile](Dockerfile)

*Follow the step-by-step [Production Deployment Guide](docs/deployment.md).*

---

## 📚 Documentation Index

- [Cloud Deployment Guide](docs/deployment.md)
- [Client Connection Guides (Claude, Cursor, VS Code, Custom GPTs)](docs/connecting/README.md)
- [Custom GPT & Gemini Gem Integration Kit](docs/connecting/custom-gpt.md)
- [API Reference Guide](docs/api-reference.md)
- [Security & Privacy Specification](docs/security.md)
- [Evaluation & Benchmark Summary](docs/evaluation.md)
- [Production Pre-Flight Checklist](docs/RELEASE_CHECKLIST.md)
- [Project Changelog](CHANGELOG.md)

---

## 📄 License

MIT © 2026 RecallFabric Authors.
