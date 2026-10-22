# Production Release Checklist

Use this checklist before cutting a release tag or deploying RecallFabric to production environments.

---

## 1. Environment & Configuration Pre-Flight

- [ ] `RECALLFABRIC_ENVIRONMENT` is set to `production`.
- [ ] `RECALLFABRIC_DATABASE_URL` is set to the cloud PostgreSQL instance with `sslmode=require`.
- [ ] `RECALLFABRIC_ADMIN_TOKEN` is set to a secure, random token (>= 32 characters).
- [ ] `RECALLFABRIC_ENCRYPTION_KEY` is set to a valid 32-byte Fernet/AES key.
- [ ] Hosted LLM credentials are set (`RECALLFABRIC_OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, or `GEMINI_API_KEY`).
- [ ] `RECALLFABRIC_RUN_MIGRATIONS` is set to `true` on web service entrypoint.
- [ ] Insecure defaults (Ollama provider, `default_admin_token`) are not active in production.

---

## 2. Database & Vector Extension

- [ ] PostgreSQL version is >= 16.
- [ ] `pgvector` extension is installed on database (`CREATE EXTENSION IF NOT EXISTS vector`).
- [ ] Connection pool parameters configured (`RECALLFABRIC_DB_POOL_PRE_PING=true`, `RECALLFABRIC_DB_POOL_RECYCLE=300`).
- [ ] `alembic upgrade head` runs cleanly without schema drift or errors.

---

## 3. Code Quality & Automated Tests

- [ ] Code formatting and linting pass cleanly:
  ```bash
  uv run ruff check .
  ```
- [ ] Full regression test suite passes:
  ```bash
  uv run pytest
  ```
- [ ] Database integration tests pass against live PostgreSQL:
  ```bash
  RECALLFABRIC_RUN_DB_TESTS=1 uv run pytest tests/test_retrieval.py tests/test_memories_api.py
  ```
- [ ] OpenAPI schema consistency validated (no drift):
  ```bash
  uv run python scripts/generate_tool_schemas.py
  ```

---

## 4. Packaging & SDKs

- [ ] Python SDK builds without errors:
  ```bash
  cd sdk/python && uv build
  ```
- [ ] JavaScript/TypeScript SDK builds and compiles typings:
  ```bash
  cd sdk/js && npm run build
  ```
- [ ] `CHANGELOG.md` updated with the new SemVer version and all notable changes.
- [ ] `pyproject.toml` version matches release tag.

---

## 5. Container Image Build

- [ ] Multi-stage Docker image builds cleanly:
  ```bash
  docker build -t recallfabric:latest .
  ```
- [ ] FastEmbed embedding model is pre-baked into `/app/.model-cache`.
- [ ] Container image size is under 1.2 GB.
- [ ] Container health check (`GET /health`) returns 200 within 5 seconds of boot.

---

## 6. Live Smoke Test Against Deployed Service

- [ ] `GET /health` returns `{"status": "ok"}`.
- [ ] `GET /v1/capabilities` returns service version and supported memory types.
- [ ] Public signup / key creation (`POST /v1/auth/signup`) returns a valid `rf_...` key.
- [ ] Memory creation (`POST /v1/remember`) stores a test fact.
- [ ] Memory recall (`POST /v1/recall`) retrieves the stored fact with similarity score.
- [ ] MCP streamable HTTP transport (`POST /mcp`) establishes session with `tools/list`.
- [ ] OpenAI-compatible memory proxy (`POST /v1/proxy/chat/completions`) successfully forwards chat completion and streams response.
- [ ] User data purge (`DELETE /v1/users/me/memories`) removes test memories completely.
