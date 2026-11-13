# RecallFabric Complete Checkout Setup Report

## 1. New project path

```text
C:\Projects\New-Recall-Fabric\Capstone-RecallFabric-Complete
```

The directory was cloned directly from the requested branch. The previous
directory was not used as a source and was not modified.

## 2. Git remote, branch, and commit

```text
Remote:  https://github.com/tusharsanka4/Capstone-RecallFabric.git
Branch:  MCP/SDK/Docker
Commit:  885478fda48d2ea297b2b6a4081d1ca64ff48b4d
Message: feat: complete modules C1-C7 (cloud DB, Docker, v1 surface, SDKs,
         MCP, proxy, and packaging)
```

The new worktree is clean and tracks `origin/MCP/SDK/Docker`.

## 3. Repository structure verification

The following paths exist and contain source or project files:

- `src/recallfabric` — 93 source files
- `tests` — 31 test files
- `sdk`
- `tools`
- `extensions/browser`
- `evaluation`
- `openapi`
- `docs`
- `migrations`
- `RecallFabric_Implementation_Plan.pdf`

The checkout also contains the candidate branch’s CI/release files, provider
adapters, security modules, MCP server, evaluation framework, browser
extension, and Python/JavaScript SDKs.

## 4. Dependency installation

Executed:

```text
uv sync --locked
```

Result: successful. The root environment installed the locked application and
development dependencies, including FastAPI, SQLAlchemy, pgvector, FastEmbed,
cryptography, MCP, pytest, matplotlib, and Ruff.

The SDK Python package is a separate project under `sdk/python`; it is not
included in the root `pyproject.toml` environment. This caused the default
test collection failure described below and should be installed separately
when SDK tests are required.

## 5. Configuration requirements

No `.env` file was copied or created. `.env.example` is present and includes
development database settings, embedding settings, provider settings,
retrieval/ranking settings, authentication, encryption, rate limiting, MCP,
and proxy configuration.

Before running a local database, supply a non-empty
`RECALLFABRIC_DB_PASSWORD` and review the database host/port/name/user values.
For production or hosted providers, configure the relevant provider API keys,
authentication/admin settings, encryption key, and direct migration database
URL. Secrets were not printed or copied.

The branch’s default `.env.example` has `RECALLFABRIC_RUN_MIGRATIONS=false`;
migrations must be run deliberately against the intended database.

## 6. Docker isolation review

No Docker service was started. The existing old stack remains running with:

- API: `127.0.0.1:8000`
- PostgreSQL: `127.0.0.1:5433`
- Volumes: `recallfabric_postgres_data` and
  `recallfabric_embedding_model_cache`

The base Compose file was rendered without starting services using the isolated
project name `recallfabric-complete` and a temporary non-secret validation
password value. Its resolved resources would be:

- Project/network: `recallfabric-complete_default`
- Database volume: `recallfabric-complete_postgres_data`
- Database host port: `5434`

The branch's checked-in `compose.yaml` defines only a `db` service. It does
not start the complete backend/API stack as-is. To validate the existing
Dockerfile without rewriting the branch's base Compose configuration, a
separate `compose.complete.yaml` override was added. It defines the API
service, uses the Docker service hostname `db` and internal port `5432`,
publishes the API on host port `8001`, enables isolated migrations, and keeps
the database on host port `5434`.

The override was rendered before startup and confirmed:

```text
Project:          recallfabric-complete
Network:          recallfabric-complete_default
Database volume:  recallfabric-complete_postgres_data
API:              127.0.0.1:8001 -> 8000
Database:         127.0.0.1:5434 -> 5432
API database host: db:5432
```

Only the new project's database and API were started. The previous project's
containers and volumes were not referenced.

The checked-in entrypoint had Windows CRLF line endings, which caused the
Linux container to fail with `exec ./entrypoint.sh: no such file or
directory`. The entrypoint was normalized to UTF-8 LF line endings in this
checkout only, then the image was rebuilt successfully.

## 7. Initial validation

Passed:

- Git branch/commit verification.
- Python compilation:
  `uv run python -m compileall -q src tests sdk tools`
- Ruff lint:
  `uv run ruff check .`
- Ruff formatting:
  `uv run ruff format --check .`
- Alembic head/history inspection:
  `3c7952fa9d14` is the head, following the initial schema, HNSW index,
  memory-events, and API-key/audit-log migrations.
- Compose isolation rendering with project name and port override.

The first default test command:

```text
uv run pytest -q
```

Result: collection stopped because `tests/test_sdk_python.py` imports
`recallfabric_client`, which is a separate package under `sdk/python` and was
not installed by the root project environment. This was fixed as test
infrastructure setup, not application behavior, by installing that package
editable into the new checkout's `.venv`.

The application test suite excluding that separate SDK test was also run:

```text
uv run pytest -q --ignore tests/test_sdk_python.py
```

Before model/database setup, the result was `120 passed, 89 skipped, 2
failed`. The failures were:

1. Ingest's local-only embedding test could not find the model cache.
2. The v1 404 test received 503 because no database was running.

The separate SDK was then installed, the FastEmbed model was downloaded into
the new checkout's `.model-cache`, and a fresh isolated database was started.
The full suite was rerun with database tests enabled:

```text
uv run pytest -q
221 passed, 1 skipped in 72.80s
```

The one skipped test was
`tests/test_memories_api.py:256`, gated by
`RECALLFABRIC_RUN_MODEL_TESTS`. It was not an external-service failure.
After enabling that flag with the downloaded model cache, the complete suite
was rerun:

```text
RECALLFABRIC_RUN_DB_TESTS=1
RECALLFABRIC_RUN_MODEL_TESTS=1
uv run pytest -q -rs
222 passed in 66.24s
```

No test was disabled or altered to obtain the passing result. The earlier
failure logs are preserved under `.audit/` for investigation.

## 8. Migration safety and database verification

The migration chain is linear and was inspected in order:

```text
0631ddfc0397  initial memory schema and pgvector extension
1a5850fbea5e  partial HNSW index for 384-dimensional embeddings
2b6941fa8c02  memory_events table and indexes
3c7952fa9d14  api_keys and audit_logs tables and indexes
```

The initial migration verifies/enables the `vector` extension and creates the
memory schema. The later migrations add the HNSW index, event provenance, API
keys, and audit logs. Encryption is configuration/runtime behavior; it does
not add a separate encryption migration.

Applied only to the new isolated database:

```text
Alembic head: 3c7952fa9d14
pgvector:     0.8.6
Tables:       memories, memory_events, api_keys, audit_logs
```

`uv run alembic check` passed with the expected SQLAlchemy warning about
comparison of the HNSW operator expression; it reported no new upgrade
operations.

## 9. API verification

The API was built from the existing Dockerfile and started through the
separate override:

```text
docker compose -p recallfabric-complete \
  -f compose.yaml -f compose.complete.yaml up -d
```

Both services reported healthy:

```text
recallfabric-complete-api-1  healthy  127.0.0.1:8001->8000/tcp
recallfabric-complete-db-1   healthy  127.0.0.1:5434->5432/tcp
```

Live endpoint checks returned HTTP 200:

- `GET http://localhost:8001/health`
- `GET http://localhost:8001/ready`
- `GET http://localhost:8001/docs`

## 10. Remaining setup notes

1. The checked-in base Compose file still contains only PostgreSQL; use the
   added override for the API until the branch configuration is intentionally
   revised.
2. Create a new `.env` from `.env.example` only after deciding the isolated
   database credentials and ports. Do not copy the old `.env`.
3. Keep using project name `recallfabric-complete`, host port 5434, and the
   automatically isolated `recallfabric-complete_postgres_data` volume.
4. Keep migrations targeted only at that new database.
5. Install the separate SDK package from `sdk/python` in fresh environments.
6. Populate the model cache through the branch's Docker/model initialization
   path before model-dependent tests.

## 11. Confirmation of backup preservation

The old project remains on branch `main` at commit `1073ab8` with its existing
uncommitted Docker, QA, and M6/M7 work. Its Git status and branch were
rechecked after cloning and remained unchanged.

No branch was switched, no old file was modified, no old configuration was
copied, no old Docker volume was deleted or recreated, no migration was run
against the old database, and no old database was modified.
