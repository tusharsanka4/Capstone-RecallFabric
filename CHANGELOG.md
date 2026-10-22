# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [1.0.0] - 2026-10-23

### Added
- **Production Packaging & Release Automation**:
  - Multi-stage uv-based Docker image pre-baking FastEmbed vector models.
  - Automated release workflow (`.github/workflows/release.yml`) publishing Python SDK (`recallfabric-client`) to PyPI, JavaScript/TypeScript SDK to npm, and Docker images to GitHub Container Registry (`ghcr.io`).
- **Multi-User Onboarding & Administration**:
  - Self-serve registration endpoint `POST /v1/auth/signup` behind configurable `allow_public_signup` flag.
  - Streamlit dashboard tab for API key generation, key revocation, usage metrics, and GDPR compliance (data export and complete memory purge).
- **Comprehensive Documentation Kit**:
  - Cloud deployment guide (`docs/deployment.md`) for Neon, Supabase, Render, Fly.io, and Railway.
  - Client connection guides (`docs/connecting/`) for Claude Desktop, Cursor, VS Code, and Custom GPTs / Gemini Gems.
  - Security model specification (`docs/security.md`) and evaluation benchmarks summary (`docs/evaluation.md`).
  - Production release checklist (`docs/RELEASE_CHECKLIST.md`).
- **Cross-Model Verification Demo**:
  - Capstone demonstration script (`scripts/demo.py`) proving cross-model memory sharing between local (Ollama) and cloud-hosted LLMs.

---

## [0.6.0] - 2026-10-23

### Added
- **OpenAI-Compatible Memory Proxy** (`POST /v1/proxy/chat/completions` and `/proxy/chat/completions`):
  - Injects relevant memory context into system messages for standard chat completion calls.
  - Full support for Server-Sent Events (SSE) streaming pass-through.
  - Resilient memory architecture: upstream completion calls never fail if database or embedding recall encounters an error.
  - Dynamic per-request upstream credentials (`X-Upstream-Key`, `Authorization`) sanitized and never logged.
  - Configurable upstream allowlist (`proxy_allowed_upstreams`) preventing SSRF.
- **Webhook Ingestion API** (`POST /v1/ingest`):
  - Asynchronous batch transcript ingestion for third-party bots and chat applications.
  - Background atomic fact extraction, deduplication, and conflict resolution with pollable status endpoint (`GET /v1/ingest/jobs/{job_id}`).
- **Browser Extension Skeleton** (`extensions/browser/`, Manifest V3):
  - Injects `🧠 Recall` button into prompt inputs on ChatGPT, Claude, and Google Gemini web interfaces.
  - Right-click context menu "Remember this with RecallFabric" to save highlighted text directly to memory.
  - Options and popup configuration pages for custom base URLs and token budgets.

---

## [0.5.0] - 2026-10-23

### Added
- **Remote Model Context Protocol (MCP) Server**:
  - Streamable HTTP transport mounted at `/mcp` alongside stdio transport for local agent use.
  - Full suite of MCP memory tools (`remember`, `recall`, `forget`, `list_memories`, `update_memory`, `get_memory_history`, `get_profile`).
  - Prompt template `use_memory` and dynamic profile resource `memory://profile`.
  - Multi-tenant session security isolating MCP sessions per authenticated user.

---

## [0.4.0] - 2026-10-23

### Added
- **Official Client SDKs**:
  - Python package `recallfabric-client` (sync and async clients with httpx, exponential backoff, typed Pydantic models).
  - JavaScript/TypeScript package `recallfabric-client` (Fetch-based, dual ESM/CJS, TypeScript typings).
  - High-level `with_memory` / `withMemory` function wrappers for automatic recall injection and non-blocking background learning.
  - Framework adapters for LangChain (`RecallFabricChatMessageHistory`, `RecallFabricRetriever`) and LlamaIndex (`RecallFabricRetriever`).

---

## [0.3.0] - 2026-10-23

### Added
- **Stable Versioned API Surface (`/v1`)**:
  - `GET /v1/capabilities`: Service version, enabled features, supported memory types, and vector dimensions.
  - Task-oriented AI tool endpoints: `POST /v1/remember`, `POST /v1/recall`, `POST /v1/forget`, and `GET /v1/profile`.
  - Native idempotency support with `Idempotency-Key` headers.
  - Clean OpenAPI 3.1 specification export with dedicated tool definitions for OpenAI, Anthropic, and Google Gemini function calling.

---

## [0.2.0] - 2026-10-23

### Added
- **Managed Cloud Database Integration**:
  - Support for managed cloud PostgreSQL (Neon, Supabase) via `RECALLFABRIC_DATABASE_URL` with SSL enforcement (`sslmode=require`) and resilient connection pool recycling (`pool_pre_ping=true`).
  - Safe Alembic pgvector extension provisioning with permission detection.
- **Production Containerization & Cloud Deployment**:
  - Multi-stage Dockerfile baking FastEmbed models into image layers to prevent cold-start download delays.
  - Production entrypoint script automating database readiness polling and migration execution.
  - Turnkey infrastructure configuration files for Render (`render.yaml`), Fly.io (`fly.toml`), and Railway (`railway.json`).

---

## [0.1.0] - 2026-10-22

### Added
- Initial core architecture:
  - Local FastAPI service with PostgreSQL (`pgvector`) vector similarity search.
  - FastEmbed local embedding pipeline (`BAAI/bge-small-en-v1.5`).
  - Automatic atomic fact extraction, deduplication locking, and LLM-driven conflict resolution.
  - Multi-factor hybrid ranking (recency, frequency, importance, relevance, confidence).
  - Claude-inspired Streamlit dashboard (`dashboard.py`).
  - Comprehensive evaluation pipeline and benchmark suites.
