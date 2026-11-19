# MCP server setup and verification

The existing server exposes eight primary memory tools and three compatibility aliases.
The server now validates content, categories, scores, UUIDs, limits, and versions;
enforces read/write scope boundaries; serializes updates/deletes against other memory
writes; and returns sanitized MCP errors (`isError=true`) for failed operations.

## Prerequisites

Follow the [canonical README setup](../README.md) for dependencies, Neon/TLS,
safe migrations, model preparation, account provisioning, and the public HTTP endpoint.
This reference retains the distinct stdio and tool-lifecycle workflows. A local Docker
database is an alternative for isolated development, not a requirement for Neon.

Use the existing administration API to create an account-scoped API key. Keep the key in
the client host's secret configuration, not in source control. The server derives account
identity from credentials; no MCP tool accepts a user identifier.

## Local stdio

Run `python -m recallfabric.mcp_server` from the repository root with:

```text
RECALLFABRIC_MCP_TRANSPORT=stdio
RECALLFABRIC_AUTH_ENABLED=true
RECALLFABRIC_API_KEY=<your account-scoped key>
```

`examples/mcp-local.example.json` is a configuration template for hosts accepting an
`mcpServers` object. Replace the placeholder key and adjust paths for the client machine.
Hosts differ in support for `cwd`; when absent, provide database configuration through
environment variables and use absolute cache paths. Do not commit a populated key file.

The official SDK probe launches a real subprocess and verifies protocol initialization,
tool discovery, resources, and prompt access without writing memories:

```powershell
uv run python scripts/mcp_probe.py
```

## Authenticated Streamable HTTP

Start the FastAPI app, which supplies authentication, OAuth scope context, session
ownership, and request-limit middleware:

```powershell
$env:RECALLFABRIC_AUTH_ENABLED = "true"
uv run uvicorn recallfabric.main:create_app --factory --host 127.0.0.1 --port 8000
```

Then, in a second terminal with `RECALLFABRIC_API_KEY` set:

```powershell
uv run python scripts/mcp_probe.py --url http://127.0.0.1:8000/mcp/
```

Selecting `RECALLFABRIC_MCP_TRANSPORT=streamable-http` in the module entry point also
launches the authenticated FastAPI app, on `RECALLFABRIC_MCP_PORT` (default 8001).
The standalone unauthenticated SSE transport is no longer supported; use stdio or
Streamable HTTP. Remote hosting needs HTTPS and the production configuration described
in `UNIVERSAL_AI_MEMORY_CONNECTOR.md`. No external agent-host installation is claimed
merely because the SDK probe passes.

## Tool lifecycle

1. `remember({"content":"User is learning Python","type":"skill"})`
2. `recall({"query":"Which programming language am I learning?","limit":5})`
3. Read the returned ID/version, then call `update_memory` with that ID,
   `expected_version`, and at least one changed field.
4. Inspect `get_memory_history` and `get_provenance`. Provenance now returns actual
   owner-scoped event records using the shared REST provenance service.
5. `forget({"memory_id":"<id>"})` previews the current revision. A semantic query may
   also preview a candidate, but only above the retrieval similarity threshold.
6. After user approval, call `forget({"memory_id":"<id>","expected_version":2,"confirm":true})`.
   This deletes only that exact revision's memory/history. A changed version gives a
   conflict; a query can never directly confirm deletion.

Read-only OAuth credentials cannot write; write-only or empty-scope OAuth credentials
cannot read a profile (including `memory://profile`). API keys retain their existing
account-scoped full-access behavior. Previewing deletion requires read and write scopes;
explicit confirmed deletion requires write permission. Tool hints describe side effects
but do not replace authorization or host-side user approval.

`remember(extract=true)` requires a working extraction provider. Provider failures and
invalid provider JSON are errors, while a valid empty list means no durable facts were found.
Stored memory text must be treated as untrusted context, never as instructions.

## Verification

No-database regression suite:

```powershell
uv run pytest -q -p no:cacheprovider tests/test_mcp_contracts.py
```

Real PostgreSQL tests create and remove only generated `test_mcp_*` schemas. They cover
authenticated HTTP lifecycle, cross-account isolation, OAuth scopes, concurrent updates,
stable deletion confirmation, and optionally real embeddings:

```powershell
$env:RECALLFABRIC_RUN_DB_TESTS = "1"
$env:RECALLFABRIC_RUN_MODEL_TESTS = "1"
uv run pytest -q -p no:cacheprovider tests/test_mcp_acceptance.py
```

## Verified local environment (2026-11-16)

Docker connectivity was restored by restarting Docker Desktop and its `docker-desktop`
WSL distribution. The database container was recreated from `compose.yaml` and is healthy
at `127.0.0.1:5433`; Alembic migrations completed successfully.

The selected MCP, OAuth metadata, and production safety suite passed **41 tests**, including
all four database acceptance tests with real local embeddings enabled. The official SDK
stdio discovery probe also passed. Acceptance tests use disposable schemas and do not
leave demo memories in the application database.
