# Memory and MCP review

Reviewed local main at `4df5ecf` on 2026-11-13. This is a code and local verification
review, not a claim that a hosted client is connected or that production is ready.

## What already exists

The repository contains both a memory engine and an MCP server. Extend the existing
implementation rather than creating a second memory store or MCP server.

```text
Agent / LLM host
  -> MCP client
  -> RecallFabric MCP tools
  -> authentication-derived user scope
  -> embeddings, retrieval/ranking, memory lifecycle operations
  -> PostgreSQL + pgvector
```

`src/recallfabric/mcp_server.py` registers eight primary tools:

| Tool | Purpose |
| --- | --- |
| remember | Store a fact, or optionally extract multiple facts from text |
| recall | Retrieve ranked memories and a formatted context string |
| update_memory | Create a revised memory |
| forget | Delete by ID or propose a semantic match for deletion |
| list_memories | Inspect stored memories |
| get_profile | Summarize active memories by category |
| get_memory_history | Inspect memory history |
| get_provenance | Expose history/provenance information |

Three compatibility aliases are also exposed: `store_memory`, `search_memory`,
and `delete_memory`. A `memory://profile` resource and a `use_memory` prompt exist.
The model selects tools; the host runs the MCP client and supplies authentication.
Tools do not expose a `user_id` argument.

The server supports a local stdio entry point. The FastAPI application in
`src/recallfabric/main.py` mounts Streamable HTTP at `/mcp`, with authentication,
scope context, and session ownership middleware. Its OAuth implementation includes
registration, authorization/PKCE, refresh, and revocation code. Remote deployment
and an actual agent-client connection still require validation.

Memory functionality is distributed across `api/memories.py`, `api/v1_tools.py`,
`services/memory_service.py`, `memory_manager/`, `embeddings/`, `ranking/`, and
`context/`. Storage, semantic search, ranking, deduplication, conflict handling,
revision history, extraction, and provenance are implemented. Optional automatic
extraction/conflict classification uses an LLM provider; local embeddings and
basic recall do not themselves require a hosted LLM key.

## Verification performed

- Synced the merged branch's dependencies using `uv sync --locked`.
- Focused tests: 51 passed, 2 skipped (embeddings, memory contracts, ranking,
  extraction, OAuth metadata, and production settings).
- Broader selection: 142 passed, 46 skipped, 45 deselected, 3 failed with
  `pytest -m 'not integration'`. The failures were the ingest worker and two SDK
  tests that access a database despite being included in that selection.
- The local SDK must be installed separately or `sdk/python` must be on
  `PYTHONPATH`; otherwise the broad test suite fails during collection.
- An official MCP SDK in-memory client successfully initialized, negotiated
  protocol `2025-11-25`, listed all 11 tools, and discovered the resource and prompt.
  This verifies protocol discovery, not database-backed tool calls.
- Docker was initially stopped. After starting it, Compose briefly reported the
  PostgreSQL container healthy. Host connections to the configured localhost
  port 5433 still timed out, and Docker's Linux engine pipe subsequently became
  unavailable. Database-backed verification and migration status remain unconfirmed.
- Application code and existing database migrations were not changed by this review.

## Issues to address before external agent use

1. **Missing profile read-scope enforcement.** `_get_profile_impl` does not call
   `require_mcp_scope('memory:read')`, unlike recall and history. Both the profile
   tool and resource reach this method. Add the check and write-only-token tests.
2. **MCP update concurrency differs from REST.** `_update_memory_impl` reads the
   current revision without the REST path's stable-row lock. `expected_version`
   is optional. Concurrent changes can fail on constraints instead of producing
   a deliberate conflict response. Share the update service and locking policy.
3. **Tool schemas are too permissive.** Discovery shows unrestricted strings for
   content/category, no 0–1 bound on importance, and no positive maximum for recall
   limits. Add shared validated request contracts and clear error responses.
4. **Extraction failure appears successful.** `remember(extract=True)` catches
   provider errors, substitutes an empty object, and returns an `extracted` result
   with zero memories. Distinguish provider failure from a valid no-facts result.
5. **Deletion by query needs a stable target.** Semantic deletion takes the nearest
   match without a relevance floor and reruns the query when `confirm=True`.
   Confirm a specific returned ID/version, and do not delete an unrelated nearest
   neighbor merely because a result exists.
6. **HTTP authentication-disabled branch has an uninitialized variable.** In the
   `/mcp` middleware, the auth-disabled path with a supplied raw key resolves a user
   but does not assign `resolved_scopes` before using it. Add a regression test.
7. **Business logic is duplicated.** MCP, task-oriented REST routes, and memory
   services implement overlapping operations. Consolidate them so behavior,
   ownership, locking, errors, and audit events stay consistent.
8. **Readiness tests contain application-side test detection.** The health module
   inspects stack-frame test names and special-cases lambda mocks. Replace that
   behavior with explicit dependency overrides and stable readiness assertions.

These are source-level findings unless explicitly listed as runtime verified above.
The review is not an exhaustive security audit.

## Recommended implementation order

1. Restore local PostgreSQL connectivity; verify/apply migrations after confirming
   the intended database, then test real embeddings with CRUD and recall.
2. Consolidate memory operations behind one service used by REST and MCP.
3. Add validated MCP input/output contracts, read/write annotations, consistent
   errors, scope checks, concurrency handling, and stable deletion confirmation.
4. Test authenticated MCP end to end: store -> recall -> update -> history -> delete,
   two independent users, read-only/write-only scopes, revoked credentials, and failures.
5. Verify stdio with a real agent host; verify the authenticated FastAPI `/mcp`
   endpoint with an SDK client. Use the FastAPI path for remote auth middleware;
   the standalone MCP transport entry point does not use that middleware.
6. Configure a chosen external client and test the same account across two hosts.
   Public hosting, provider credentials, and client installation are separate steps.
