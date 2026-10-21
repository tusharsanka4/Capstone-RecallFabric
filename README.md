# RecallFabric

RecallFabric is a standalone memory service for AI applications. The AI model generates
answers; RecallFabric stores, retrieves, ranks, and manages persistent context.

Milestones 1–9 provide the Python/FastAPI foundation, PostgreSQL with pgvector,
a versioned memory schema, CRUD with text search, local embedding generation,
semantic retrieval with cosine ranking and similarity cutoff, atomic fact extraction
from conversation text using local LLMs (Ollama), and a Streamlit dashboard.

## Local setup

Use Python 3.12, the `uv` package manager, and Docker Desktop with Linux containers.
Start Docker Desktop, then run these commands from the project root
in PowerShell. `uv sync` installs the pinned Python version if necessary and creates `.venv`.
The local cache paths keep downloaded tooling inside the project.

```powershell
$env:UV_CACHE_DIR = "$PWD\.uv-cache"
$env:UV_PYTHON_INSTALL_DIR = "$PWD\.uv-python"
uv sync --locked
Copy-Item .env.example .env
docker compose up -d --wait
uv run alembic upgrade head
uv run python -m recallfabric.embeddings --download
uv run uvicorn recallfabric.main:create_app --factory --reload
```

Copy `.env.example` only on first setup to avoid replacing existing settings.
Open <http://127.0.0.1:8000/docs> for the interactive API documentation.
`GET /health` returns `{"status":"ok"}` when the service is running. This endpoint checks
process liveness only; it does not check a database or an AI provider.
`GET /ready` checks database connectivity and whether the vector extension is enabled.
It returns HTTP 503 if either is unavailable. The app can start while the database is
offline, allowing liveness checks to remain available.

To start the interactive chat UI dashboard:

```powershell
uv run streamlit run dashboard.py
```

## Database

The Compose service uses PostgreSQL 17 with pgvector 0.8.6, following the
[official pgvector Docker setup](https://github.com/pgvector/pgvector#docker).
It binds to `127.0.0.1` and stores data in the `recallfabric_postgres_data` Docker volume.
The initialization SQL enables `vector` when the volume is first created.
The example credentials are for local development; the container's database user is
an administrator. Deployment credentials and a restricted application role belong
in a deployment-specific configuration.

```powershell
docker compose ps
docker compose stop
docker compose up -d --wait
```

Stopping or recreating the container preserves the named volume. Avoid `docker compose
down -v` unless you intend to delete the database. Changing credentials in `.env` does
not change users in an existing database volume. If port 5432 is occupied, set
`RECALLFABRIC_DB_PORT=5433` in `.env` before starting Compose; the app reads the same value.

For an existing PostgreSQL instance, install pgvector on the server and run
`CREATE EXTENSION IF NOT EXISTS vector;` as an administrator in the target database.
Set the `RECALLFABRIC_DB_*` variables to connect to it. The app does not create extensions
or tables at startup. SQLAlchemy manages the connection pool and releases it at shutdown.

## Memory schema and migrations

Run `uv run alembic upgrade head` after starting the database and after pulling new
migrations. `uv run alembic current` shows the installed revision; `uv run alembic check`
checks for model changes that need a migration. Alembic uses the same `.env` as the app.
pgvector must already be enabled by milestone 2. `/ready` checks database and
extension availability, not migration status.

The `memories` table stores one row per revision, with `(id, version)` as its primary key.

| Fields | Meaning |
| --- | --- |
| `id`, `user_id` | Stable memory UUID and external user identifier |
| `version`, `previous_version` | Positive revision number and predecessor link |
| `content`, `type` | Text and category: preference, goal, skill, profile, fact, or other |
| `importance`, `confidence` | Scores between 0 and 1, defaulting to 0.5 and 1.0 |
| `source`, `creation_reason` | Required source reference and optional explanation |
| `status` | `active`, `disabled`, or `superseded` |
| `metadata` | JSON object for extra attributes; named `attributes` in the ORM |
| `embedding`, `embedding_model`, `embedding_dimensions` | Optional vector and its model identity/size |
| `created_at`, `updated_at` | Timezone-aware timestamps for this revision; updates use a DB trigger |
| `access_count`, `last_accessed_at` | Access tracking fields for future ranking logic |

New memories start at version 1. The update endpoint marks
the current row `superseded` and inserts the next version in the same transaction,
reusing the ID and owner and linking `previous_version`. The database enforces sequential
predecessor links, the same owner across revisions, and at most one active or disabled
revision per ID. It does not automatically copy rows into history or prevent direct edits;
the API implements the revision-writing workflow.

Ownership columns and indexes support user-scoped queries; they do not enforce access
authorization. The development API scopes every query to the supplied `user_id`.
Authentication is not implemented yet: callers can supply any user ID. Trusted local
development is the intended use until authentication and permissions are added.
Hard deletion removes all revisions of a memory together.

### Vector indexing and limitations

An HNSW index (`vector_cosine_ops`) is defined on `(embedding::vector(384))` with a
partial index condition `WHERE embedding_dimensions = 384`.

**Limitation**: Because the `embedding` column supports arbitrary vector dimensions,
pgvector requires explicit dimensions for HNSW indexes. The index specifically covers
the configured 384-dimensional model (`BAAI/bge-small-en-v1.5`). Memories stored with
different embedding dimensions will not be indexed by this HNSW index and will fall back
to sequential scans unless additional dimension-specific partial indexes are added.

## Memory API

All endpoints are available in `/docs`. Supply `user_id` in POST bodies and as a query
parameter for GET, PUT, and DELETE requests. IDs are UUIDs; missing memories and memories
outside the supplied owner scope both return 404.

| Method and path | Behavior |
| --- | --- |
| `POST /memories` | Create revision 1; return 201 and a Location header |
| `GET /memories` | List current active/disabled memories, with optional `type` and `status` filters |
| `GET /memories/{id}` | Read the current revision |
| `PUT /memories/{id}` | Replace writable fields and create the next revision |
| `DELETE /memories/{id}` | Permanently delete every revision; return 204 |
| `POST /memories/search` | Case-insensitive literal substring search over current memory content |
| `GET /memories/{id}/versions` | Read revision history, newest version first |
| `POST /memories/retrieve` | Semantic retrieval with cosine similarity ranking and optional `min_score` cutoff |
| `POST /extraction` | Extract atomic facts from unstructured text using LLM and store in one transaction |
| `POST /chat` | Chat with LLM using ranked persistent memory context and optional turn extraction |
| `GET /providers` | List configured LLM providers and reachability status without exposing secrets |
| `POST /auth/keys` | Create user API key (admin protected by `RECALLFABRIC_ADMIN_TOKEN`) |
| `GET /auth/keys` | List API keys and revocation metadata without secrets |
| `DELETE /auth/keys/{id}` | Revoke an API key |
| `DELETE /users/me/memories` | Bulk delete all memories and event records for the authenticated user |
| `GET /users/me/export` | Export complete memory revisions and provenance history as JSON |

### Semantic Retrieval (`POST /memories/retrieve`)

Retrieves candidates via vector cosine similarity, re-ranks them using a pure multi-signal scoring model, and returns the top `limit` records:

$$\text{Score} = w_{\text{rel}} \cdot \text{relevance} + w_{\text{imp}} \cdot \text{importance} + w_{\text{conf}} \cdot \text{confidence} + w_{\text{rec}} \cdot \text{recency} + w_{\text{freq}} \cdot \text{frequency}$$

Signals are normalized to $[0, 1]$ and weighted (weights default to summing to 1.0):
- **Relevance**: Cosine similarity clamped to $[0.0, 1.0]$.
- **Importance**: Memory importance score in $[0.0, 1.0]$.
- **Confidence**: Memory confidence score in $[0.0, 1.0]$.
- **Recency**: Exponential decay based on age in days: $2^{-\Delta t / t_{\text{half}}}$ where $t_{\text{half}}$ is `RECALLFABRIC_RANK_RECENCY_HALF_LIFE_DAYS`.
- **Frequency**: Log-scaled access count normalized against `RECALLFABRIC_RANK_FREQUENCY_CAP`: $\frac{\ln(1 + \min(\text{access\_count}, C))}{\ln(1 + C)}$.

Request payload:

```json
{
  "user_id": "alice",
  "query": "What programming languages does the user know?",
  "type": "skill",
  "status": "active",
  "limit": 10,
  "min_score": 0.4,
  "track_access": true
}
```

- `min_score`: Optional cosine similarity cutoff. When omitted, defaults to `RECALLFABRIC_RETRIEVAL_MIN_SIMILARITY` (0.4). Memories with cosine similarity below this threshold are omitted.
- `track_access`: Boolean flag (defaults to `true`). When enabled, atomically increments `access_count` and sets `last_accessed_at = now()` for all returned memories in the same request.
- `has_more`: Boolean indicator accurately reflecting whether additional matching records exist beyond `limit`.
- `score_breakdown`: Returned on each `MemoryRanked` item containing individual signal scores (`relevance`, `importance`, `confidence`, `recency`, `frequency`) alongside the combined `score`.

### Fact Extraction (`POST /extraction`)

Extracts atomic, declarative facts from conversational text using an OpenAI-compatible LLM
(e.g., local Ollama instance with `qwen2.5:0.5b`).

Request payload:

```json
{
  "user_id": "alice",
  "text": "I work as a software engineer in Seattle and I love Python.",
  "source": "conversation_42",
  "dry_run": false
}
```

- **Quality Filtering**: Rejects temporary/situational states (e.g. "I am hungry right now", "I'm in a meeting"), questions, conversational greetings, assistant/AI boilerplate, and statements not in the third person starting with "User".
- **Configurable Thresholds**: Filters facts below `RECALLFABRIC_EXTRACTION_MIN_IMPORTANCE` (0.6) and `RECALLFABRIC_EXTRACTION_MIN_CONFIDENCE` (0.5).
- **Dry Run**: When `dry_run: true`, runs LLM extraction and filter pipeline, returning parsed `candidates` and `rejected` candidates with reasons without modifying database state.
- **Transactional Persistence**: When not a dry run, extracts all candidate memories, generates embeddings, and writes all records within a single database transaction (rolls back entirely if any record fails).
- **Error Mapping**: Returns HTTP 503 if LLM is unreachable, 504 on timeout, 502 if LLM returns invalid JSON or structure, and 422 for invalid input.


### Chat (`POST /chat`)

Retrieves relevant memories, builds a token/character budgeted context block, and prompts the LLM:

Request payload:

```json
{
  "user_id": "alice",
  "message": "What do I like to eat?",
  "history": [
    {"role": "user", "content": "Hi"},
    {"role": "assistant", "content": "Hello! How can I help?"}
  ],
  "conversation_id": "conv_1",
  "extract": true
}
```

- Retrieves top memories via `/memories/retrieve`, then uses `recallfabric.context.builder` to assemble context up to `RECALLFABRIC_CONTEXT_MAX_CHARS` (dropping lowest-ranked memories first when over budget).
- Trims conversation history to `RECALLFABRIC_CHAT_HISTORY_LIMIT` (default 6).
- Prompts OpenAI-compatible chat model (`RECALLFABRIC_CHAT_MODEL`, default `qwen2.5:0.5b`).
- When `extract` is `true`, runs fact extraction on the user message after generating the reply and includes created memories in the response.
- Returns HTTP 503 if LLM is unreachable and 504 on timeout.
- Response includes `{reply, memories_used, model, extracted}`.

## Local embeddings

The default is FastEmbed's CPU-based `BAAI/bge-small-en-v1.5` model, producing 384-dimensional
vectors. No API key is needed. The setup command downloads model artifacts into the ignored
`.model-cache` folder; inference runs locally. HTTP requests load cached files only and never
download models. See [FastEmbed's quickstart](https://qdrant.tech/documentation/fastembed/fastembed-quickstart/)
and [query/passage embedding guidance](https://qdrant.github.io/fastembed/qdrant/Retrieval_with_FastEmbed/).

```powershell
# First setup, or after changing the model:
uv run python -m recallfabric.embeddings --download
# Verify cached inference without downloading:
uv run python -m recallfabric.embeddings
```

`POST /embeddings` prepares a query vector by default:

```json
{"text": "Which framework is the user learning?", "kind": "query"}
```

## Configuration

Settings are read from `.env` and environment variables, with environment variables
taking precedence. Keep secrets out of version control; `.env` is ignored.

| Variable | Default | Accepted values |
| --- | --- | --- |
| `RECALLFABRIC_APP_NAME` | `RecallFabric` | Any nonempty string |
| `RECALLFABRIC_ENVIRONMENT` | `development` | `development`, `test`, `production` |
| `RECALLFABRIC_LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` |
| `RECALLFABRIC_DB_HOST` | `127.0.0.1` | Database hostname |
| `RECALLFABRIC_DB_PORT` | `5432` | Port between 1 and 65535 |
| `RECALLFABRIC_DB_NAME` | `recallfabric` | Database name |
| `RECALLFABRIC_DB_USER` | `recallfabric` | Database username |
| `RECALLFABRIC_DB_PASSWORD` | Empty | Set in `.env`; required by Compose |
| `RECALLFABRIC_DB_CONNECT_TIMEOUT` | `3` | Connection and pool wait timeout, 1–60 seconds |
| `RECALLFABRIC_EMBEDDING_MODEL` | `BAAI/bge-small-en-v1.5` | Supported FastEmbed dense text model |
| `RECALLFABRIC_EMBEDDING_CACHE_DIR` | `.model-cache` | Local model cache path |
| `RECALLFABRIC_EMBEDDING_THREADS` | `2` | CPU inference threads, 1–32 |
| `RECALLFABRIC_LLM_BASE_URL` | `http://127.0.0.1:11434/v1` | OpenAI-compatible endpoint URL |
| `RECALLFABRIC_EXTRACTION_MODEL` | `qwen2.5:0.5b` | Model name for extraction completions |
| `RECALLFABRIC_CHAT_MODEL` | `qwen2.5:0.5b` | Model name for chat completions |
| `RECALLFABRIC_LLM_API_KEY` | `ollama` | API key for LLM service |
| `RECALLFABRIC_LLM_TIMEOUT` | `30.0` | Timeout in seconds for LLM calls (1.0–600.0) |
| `RECALLFABRIC_EXTRACTION_TEMPERATURE` | `0.0` | Sampling temperature for extraction (0.0–2.0) |
| `RECALLFABRIC_EXTRACTION_MIN_IMPORTANCE` | `0.6` | Minimum importance score for extracted memories (0.0–1.0) |
| `RECALLFABRIC_EXTRACTION_MIN_CONFIDENCE` | `0.5` | Minimum confidence score for extracted memories (0.0–1.0) |
| `RECALLFABRIC_CONTEXT_MAX_CHARS` | `2000` | Max character budget for retrieved context block (>= 100) |
| `RECALLFABRIC_RETRIEVAL_MIN_SIMILARITY` | `0.4` | Default minimum cosine similarity cutoff (-1.0 to 1.0) |
| `RECALLFABRIC_RANK_W_RELEVANCE` | `0.40` | Relevance weight in ranking score (0.0 to 1.0, weights must sum to 1.0) |
| `RECALLFABRIC_RANK_W_IMPORTANCE` | `0.20` | Importance weight in ranking score (0.0 to 1.0) |
| `RECALLFABRIC_RANK_W_CONFIDENCE` | `0.10` | Confidence weight in ranking score (0.0 to 1.0) |
| `RECALLFABRIC_RANK_W_RECENCY` | `0.15` | Recency weight in ranking score (0.0 to 1.0) |
| `RECALLFABRIC_RANK_W_FREQUENCY` | `0.15` | Frequency weight in ranking score (0.0 to 1.0) |
| `RECALLFABRIC_RANK_RECENCY_HALF_LIFE_DAYS` | `14.0` | Exponential decay half-life in days (> 0.0) |
| `RECALLFABRIC_RANK_FREQUENCY_CAP` | `100` | Access count cap for log-normalized frequency (>= 1) |
| `RECALLFABRIC_RANK_CANDIDATE_MULTIPLIER` | `3` | Multiplier for vector candidate top-K fetch before re-ranking (>= 1) |
| `RECALLFABRIC_DEDUPE_THRESHOLD` | `0.92` | Cosine similarity threshold for memory deduplication (0.0–1.0) |
| `RECALLFABRIC_CONFLICT_MIN_SIMILARITY` | `0.70` | Cosine similarity lower bound for LLM conflict detection (0.0–1.0) |
| `RECALLFABRIC_EXTRACTION_MAX_SNIPPET_CHARS` | `200` | Max character length for extraction snippet reference (10–2000) |
| `RECALLFABRIC_LLM_PROVIDER` | `ollama` | Default LLM provider (`ollama`, `openai`, `anthropic`, `gemini`) |
| `RECALLFABRIC_CHAT_PROVIDER` | None | Chat LLM provider (falls back to `RECALLFABRIC_LLM_PROVIDER`) |
| `RECALLFABRIC_EXTRACTION_PROVIDER` | None | Extraction LLM provider (falls back to `RECALLFABRIC_LLM_PROVIDER`) |
| `RECALLFABRIC_OPENAI_API_KEY` | None | OpenAI API key (SecretStr, never logged) |
| `RECALLFABRIC_OPENAI_BASE_URL` | None | Custom base URL for OpenAI endpoint |
| `RECALLFABRIC_OPENAI_MODEL` | `gpt-4o-mini` | Default model for OpenAI provider |
| `RECALLFABRIC_ANTHROPIC_API_KEY` | None | Anthropic API key (SecretStr, never logged) |
| `RECALLFABRIC_ANTHROPIC_BASE_URL` | `https://api.anthropic.com` | Base URL for Anthropic Messages API |
| `RECALLFABRIC_ANTHROPIC_MODEL` | `claude-3-5-sonnet-latest` | Default model for Anthropic provider |
| `RECALLFABRIC_GEMINI_API_KEY` | None | Google Gemini API key (SecretStr, never logged) |
| `RECALLFABRIC_GEMINI_MODEL` | `gemini-1.5-flash` | Default model for Gemini provider |
| `RECALLFABRIC_AUTH_ENABLED` | `false` (dev), `true` (prod) | Require API key authentication for all endpoints |
| `RECALLFABRIC_ADMIN_TOKEN` | None | Secret token for administrative API key management |
| `RECALLFABRIC_ENCRYPTION_KEY` | None | Base64 Fernet key for optional field-level content encryption at rest |
| `RECALLFABRIC_RATE_LIMIT_RPS` | `20.0` | Max sustained requests per second per key/client |
| `RECALLFABRIC_RATE_LIMIT_BURST` | `40` | Max burst capacity for token bucket rate limiter |
| `RECALLFABRIC_MAX_REQUEST_SIZE_BYTES` | `1048576` | Max request payload body size in bytes (HTTP 413 on overflow) |
| `RECALLFABRIC_API_KEY` | None | Client API key for dashboard and API consumers |

## Security and Privacy

### TLS Termination & Network Security
RecallFabric is designed as a standalone microservice. In production deployments, TLS should be terminated at a reverse proxy (e.g., Nginx, Caddy, Envoy, or cloud load balancers such as AWS ALB or GCP Cloud Load Balancing) that routes traffic over HTTPS and terminates certificates before forwarding traffic to the application.

### PostgreSQL Disk Encryption
To protect database storage at rest, enable disk-level encryption on the PostgreSQL host or volume:
- **Cloud Databases**: Enable AWS KMS storage encryption for RDS/Aurora, GCP Cloud SQL encryption, or Azure Database for PostgreSQL encrypted storage.
- **Self-Hosted / Docker**: Place the `recallfabric_postgres_data` volume on an encrypted filesystem (e.g., Linux LUKS dm-crypt or encrypted ZFS/btrfs pool).

### Field-Level Encryption at Rest
RecallFabric supports optional field-level encryption of memory `content` at rest using symmetric 32-byte Fernet keys (`RECALLFABRIC_ENCRYPTION_KEY`).
- **How it works**: Before saving to PostgreSQL, the memory content is encrypted (`enc::<ciphertext>`) and transparently decrypted when fetched via read, retrieval, or export endpoints.
- **Tradeoff & Vector Search**: Vector embeddings are generated on plaintext before encryption and stored in vector representation (`pgvector`). As a result, semantic vector search (`POST /memories/retrieve`) remains completely functional without compromising search speed. However, literal database substring search (`POST /memories/search` with SQL `ILIKE`) does not match raw ciphertexts directly.

### User Isolation & Audit Logging
- When `RECALLFABRIC_AUTH_ENABLED=true`, every memory, extraction, chat, retrieve, and provenance endpoint validates the caller's API key. Mismatches between the authenticated user and target data return HTTP 403 Forbidden.
- All authentication failures, API key creations and revocations, bulk deletions, and user exports are recorded in the `audit_logs` table. Secrets, passwords, and private keys are never included in audit records, error responses, or application logs.

## Model Context Protocol (MCP) Server

RecallFabric includes an official Model Context Protocol (MCP) server at `src/recallfabric/mcp_server.py` using the Python MCP SDK. It exposes memory management tools directly to LLM clients (such as Claude Desktop, Cursor, or autonomous agent loops) via standard stdio or streamable HTTP.

### Available Tools

- `store_memory(content, type, importance, confidence, source)`: Stores a memory using the internal memory manager (with automated deduplication and provenance events).
- `search_memory(query, limit, type)`: Performs multi-signal semantic retrieval and ranking over user memories.
- `update_memory(id, content, expected_version)`: Updates an existing memory revision with optimistic version concurrency.
- `delete_memory(id)`: Deletes all revisions of a memory and appends a tombstone provenance event.
- `list_memories(type, status)`: Lists current memories for the user.
- `get_memory_history(id)`: Retrieves full revision history for a memory.

### Claude Desktop Configuration

Add RecallFabric to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "recallfabric": {
      "command": "uv",
      "args": [
        "--directory",
        "C:\\Users\\PC01\\Desktop\\Aarush\\COLLEGE\\Projects\\capstone",
        "run",
        "python",
        "-m",
        "recallfabric.mcp_server"
      ],
      "env": {
        "RECALLFABRIC_API_KEY": "rf_your_api_key_here",
        "RECALLFABRIC_USER_ID": "alice"
      }
    }
  }
}
```

### PowerShell Smoke Test

Run this PowerShell command to verify tool registration and execution over the in-memory MCP pipeline:

```powershell
$env:RECALLFABRIC_USER_ID = "smoke_test_user"
uv run python -c "from recallfabric.mcp_server import create_mcp_server; import asyncio; s = create_mcp_server(); asyncio.run(s.call_tool('store_memory', {'content': 'User is learning Rust', 'type': 'skill'})); res = asyncio.run(s.call_tool('search_memory', {'query': 'what is the user learning'})); print(res)"
```

## Development checks

```powershell
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

Unit tests run without a database. To include integration tests:

```powershell
docker compose up -d --wait
$env:RECALLFABRIC_RUN_DB_TESTS = "1"
uv run pytest
Remove-Item Env:RECALLFABRIC_RUN_DB_TESTS
```

## Dashboard Manual Test Checklist

Run the Streamlit dashboard:

```powershell
uv run streamlit run dashboard.py
```

Verify the following end-to-end user workflows:
1. **Creation**:
   - Navigate to the **🧠 Memories** tab.
   - Expand **➕ Create New Memory**.
   - Enter content (e.g. `User drinks pour-over Ethiopian coffee`), set type to `preference`, adjust sliders, and click **Create Memory**.
   - Verify the created memory appears in the sidebar and catalog.
2. **Catalog & Filtering**:
   - Filter by type (e.g. `preference`, `fact`) and verify filtered results.
   - Filter by status (`active` vs `disabled`).
   - Test pagination using `◀ Previous` and `Next ▶` controls.
3. **Semantic & Plain-text Search**:
   - Enter a search query with semantic search (toggle off) and verify score breakdown (`relevance`, `importance`, `confidence`, `recency`, `frequency`).
   - Toggle **Plain-text search** on and verify substring search matches.
4. **Edit & Conflict Handling**:
   - Under **Manage Selected Memory**, expand **✏️ Edit Memory Content / Attributes**.
   - Modify content and save; verify new revision number.
   - If version conflicts occur (409), verify warning notification and automatic reload.
5. **Disable & Enable**:
   - Click **🚫 Disable Memory**; verify status changes to `disabled`.
   - Click **✅ Enable Memory**; verify status restores to `active`.
6. **History & Provenance Inspection**:
   - Expand **📜 Version History (/versions)** to review chronological revisions.
   - Expand **🔍 Provenance Feed (/provenance)** to inspect event sequence (`CREATED`, `SUPERSEDED`, `DISABLED`, etc.).
7. **Extraction Preview**:
   - In **🔬 Extraction Preview Panel**, paste conversational text and click **Preview Extraction**.
   - Verify candidate extractions and filter rejections are previewed without database writes.
8. **Delete with Confirmation**:
   - Verify delete button is disabled until **Confirm permanent deletion** is checked.
   - Delete the memory and verify immediate catalog update.
9. **Clear All Confirmation**:
   - In the sidebar, click **✕ Clear** and verify the confirmation prompt.
   - Confirm deletion to wipe all user memories.

## Project layout

```text
src/recallfabric/
  main.py          Application factory
  dashboard_client.py Plain HTTP helper functions for UI and client consumers
  api/health.py    Liveness and database readiness endpoints
  api/memories.py  CRUD, history, search, and semantic retrieval endpoints
  api/embeddings.py Query and passage embedding endpoint
  api/extraction.py Memory extraction endpoint with quality filters and LLM client
  api/chat.py      Chat endpoint connecting persistent memory to LLM
  api/provenance.py Provenance feed and history endpoints
  api/providers.py List configured providers and reachability endpoint
  api/auth.py      API key creation, listing, and revocation endpoints
  api/users.py     User data export and bulk deletion endpoints
  security/        Authentication, rate limiting, encryption, and audit logging
  providers/       Model-independent LLM provider layer (Ollama, OpenAI, Anthropic, Gemini)
  extraction/      Quality filters and extraction prompt
  context/         Budgeted context block builder and system prompt assembly
  embeddings/     Local model adapter and download/verification command
  memory_manager/  Memory deduplication, consolidation, conflicts, and events
  ranking/         Pure DB-independent scoring and decay functions
  core/config.py   Environment settings
  db/connection.py PostgreSQL engine and readiness query
  db/models.py     Versioned memory and memory events models and constraints
  db/session.py    Request sessions and sanitized database errors
  schemas/memory.py Validated memory input/output contracts
  schemas/chat.py  Chat message and request/response contracts
  schemas/provenance.py Memory events and provenance feed contracts
  schemas/provider.py Provider information response contracts
  schemas/auth.py  API key management request and response contracts
dashboard.py       Streamlit chat interface and memory management view
migrations/        Alembic migrations and timestamp trigger
docker/postgres/   First-start extension initialization
compose.yaml       Local PostgreSQL service and persistent volume
tests/             Unit and opt-in database integration checks
pyproject.toml     Package, dependencies, and development tooling
```

See `RecallFabric_Implementation_Plan.pdf` for the full implementation roadmap.
