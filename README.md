# RecallFabric

RecallFabric is a standalone memory service for AI applications. The AI model generates
answers; RecallFabric stores, retrieves, ranks, and manages persistent context.

Milestones 1–5 provide the Python/FastAPI foundation, PostgreSQL with pgvector,
a versioned memory schema, CRUD with text search, and local embedding generation.

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
pgvector must already be enabled by milestone 2. `/ready` currently checks database and
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

Legacy vectors can remain null until those memories are updated. New API writes generate
embeddings before committing. When supplied, all three embedding
fields are required and the declared size must match the vector. Dimensions are not fixed
to a provider yet. Retrieval must filter by embedding model and dimensions before comparing
vectors. Approximate vector indexes will be added when the embedding model and retrieval
requirements are selected; current indexes cover owner/status/type and owner/creation time.

Pydantic `MemoryCreate` and `MemoryRead` contracts validate input and serialize stored
records. Internal fields such as status, version, and embeddings cannot be set through
`MemoryCreate`. For migration development, use `uv run alembic revision --autogenerate -m
"description"` and review the generated code, especially custom constraints and triggers.
Migration rollback deletes the memory table; use downgrade only on disposable databases.

Implementation references: [Alembic migrations](https://alembic.sqlalchemy.org/en/latest/tutorial.html)
and [pgvector's SQLAlchemy adapter](https://github.com/pgvector/pgvector-python#sqlalchemy).

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

List, history, and search responses contain `items`, `limit`, `offset`, and `has_more`.
The default page size is 20 and the maximum is 100. Lists and search results sort by
revision creation time descending, with UUID/version tie-breakers. Search defaults to
active memories and optionally accepts `type` and `status`. `%` and `_` are literal search
characters. Semantic search follows in milestone 6.

PUT requires `content`, `type`, `source`, and `expected_version`. It is a full replacement:
omitted optional values reset to defaults (`importance=0.5`, `confidence=1`, `metadata={}`,
`creation_reason=null`, `status=active`). Ownership cannot change. A stale version returns
409; writes lock the first revision to serialize updates and deletion. A failed write
rolls back the whole transaction. Changed content generates a new embedding;
unchanged content retains it only when its model identity and dimensions match the current
configuration. Missing or incompatible embeddings are regenerated. Access counters start
at zero for each revision and are
reserved for the later ranking milestone.

Invalid requests return 422. Database constraint conflicts return 409; connectivity failures
return 503, without database details in responses.

Example in PowerShell after starting the server:

```powershell
$baseUrl = 'http://127.0.0.1:8000'
$body = @{
    user_id = 'user_123'
    content = 'User is learning Spring Boot'
    type = 'skill'
    source = 'conversation_102'
} | ConvertTo-Json
$memory = Invoke-RestMethod "$baseUrl/memories" -Method Post -ContentType 'application/json' -Body $body
Invoke-RestMethod "$baseUrl/memories/$($memory.id)?user_id=user_123"

$replacement = @{
    content = 'User is learning Django'
    type = 'skill'
    source = 'conversation_103'
    expected_version = $memory.version
} | ConvertTo-Json
Invoke-RestMethod "$baseUrl/memories/$($memory.id)?user_id=user_123" -Method Put -ContentType 'application/json' -Body $replacement
Invoke-RestMethod "$baseUrl/memories/$($memory.id)/versions?user_id=user_123"

$search = @{ user_id = 'user_123'; query = 'Django' } | ConvertTo-Json
Invoke-RestMethod "$baseUrl/memories/search" -Method Post -ContentType 'application/json' -Body $search
Invoke-RestMethod "$baseUrl/memories/$($memory.id)?user_id=user_123" -Method Delete
```

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

POST and content-changing PUT operations generate a passage vector before opening their
write transaction. PUT checks ownership and the expected version both before inference
and after acquiring the write lock. Concurrent edits may perform duplicate inference, but
only one update of the same version commits. Existing historical vectors remain intact.
Model loading/inference failures return 503 without creating or superseding a revision.
Reads, text search, deletion, and process health do not require loaded model weights.

`POST /embeddings` prepares a query vector by default:

```json
{"text": "Which framework is the user learning?", "kind": "query"}
```

The response contains `model`, `dimensions`, and `vector`. Use `kind: "passage"` to embed a
document with the same pipeline used by memory writes. The endpoint does not store text or
search the database. Inputs must be nonempty and at most 20,000 characters. Memory responses
include model identity and dimensions but omit the vector itself.

The default model is intended for English and truncates inputs to its token window (512
tokens); keep memories concise. Full original content is still stored. Model inference is
serialized per app process; worker processes load separate model copies. The model's
`fastembed:`-prefixed identity and dimension are stored alongside every generated vector.
To backfill a legacy memory or switch models, PUT its current fields with its current
`expected_version`; this creates a new revision with the configured embedding. Historical
revisions are not backfilled automatically.

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

The log level configures application logging. Configure Uvicorn's server logging with
its `--log-level` option. The environment label does not configure deployment security.

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

The integration tests verify live readiness, vector storage, and nearest-neighbor
ordering. Schema tests apply the real migration in isolated test schemas, verify revision
history and constraints, and exercise downgrade/re-upgrade. Their transactions roll back
on completion, leaving application records unchanged.
API tests use separate temporary schemas with real commits to exercise CRUD, ownership
filters, pagination, search, rollback, and concurrent writes, then remove those test schemas.
Standard tests use a deterministic embedding test double and do not download or load model
weights. To include the real-model/API/database round-trip check after downloading the model,
set both `RECALLFABRIC_RUN_DB_TESTS=1` and `RECALLFABRIC_RUN_MODEL_TESTS=1` before running pytest.

Commit `uv.lock` to keep dependency versions reproducible across the team.

## Project layout

```text
src/recallfabric/
  main.py          Application factory
  api/health.py    Liveness and database readiness endpoints
  api/memories.py  CRUD, history, and text search endpoints
  api/embeddings.py Query and passage embedding endpoint
  embeddings/     Local model adapter and download/verification command
  core/config.py   Environment settings
  db/connection.py PostgreSQL engine and readiness query
  db/models.py     Versioned memory model and constraints
  db/session.py    Request sessions and sanitized database errors
  schemas/memory.py Validated memory input/output contracts
migrations/        Alembic migrations and timestamp trigger
docker/postgres/   First-start extension initialization
compose.yaml       Local PostgreSQL service and persistent volume
tests/             Unit and opt-in database integration checks
pyproject.toml     Package, dependencies, and development tooling
```

See `RecallFabric_Implementation_Plan.pdf` for the full implementation roadmap.
