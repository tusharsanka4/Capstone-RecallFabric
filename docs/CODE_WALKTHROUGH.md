# Explaining RecallFabric's code

Read the code in the order a request travels, rather than by file size.

| Component | Entry point | Responsibility |
|---|---|---|
| Application | `src/recallfabric/main.py` | Assemble routes, database engine, middleware, and MCP lifecycle. |
| Configuration | `src/recallfabric/core/config.py` | Load environment settings and reject unsafe production configuration. |
| Accounts and OAuth | `src/recallfabric/api/auth.py` | Provision keys, verify consent, and issue resource-bound client credentials. |
| Authorization | `src/recallfabric/security/auth.py` | Validate credentials and enforce account ownership. |
| MCP tools | `src/recallfabric/mcp_server.py` | Expose remember, recall, revision, profile, provenance, and deletion operations. |
| Tool errors | `src/recallfabric/mcp_contracts.py` | Bound inputs and convert internal failures into safe MCP errors. |
| REST operations | `src/recallfabric/api/memories.py` | Provide dashboard/SDK memory endpoints. |
| Storage helpers | `src/recallfabric/services/memory_service.py` | Implement account-scoped queries and persistence. |
| Revision locking | `src/recallfabric/services/locking.py` | Serialize conflicting writes before checking the expected version. |
| Memory management | `src/recallfabric/memory_manager/` | Deduplicate facts, resolve conflicts, identify projects, and record events. |
| Embeddings | `src/recallfabric/embeddings/service.py` | Convert passages and queries into compatible vectors. |
| Ranking | `src/recallfabric/ranking/scoring.py` | Combine relevance with other configured ranking signals. |
| Database | `src/recallfabric/db/` and `migrations/` | Define records, pooled connections, TLS checks, and schema upgrades. |
| Dashboard chat | `src/recallfabric/api/chat.py` | Retrieve context, request an LLM response, and optionally extract facts. |
| Extraction | `src/recallfabric/api/extraction.py` and `extraction/` | Validate proposed facts and explicitly accepted decisions before storage. |
| LLM adapters | `src/recallfabric/providers/` | Translate common chat requests into provider-specific APIs. |
| Dashboard | `dashboard.py` and `src/recallfabric/dashboard_client.py` | Render UI and call REST endpoints; do not access PostgreSQL directly. |

## Saving and retrieving

An MCP write reaches authentication first. A validated credential supplies the
account identity through a ContextVar, so simultaneous requests do not share a
mutable global user. The tool checks its inputs, processes the memory, creates an
embedding, and persists the record within a transaction. Locks prevent conflicting
writes from racing through revision or deduplication decisions.

Recall embeds the question, searches only the authenticated account's eligible
records, filters irrelevant matches, and ranks the remaining results. A limit is
a maximum count, not a requirement to return irrelevant records. Project matching
adds context but never substitutes for the ownership filter.

The database stores vectors; the configured embedding provider generates them.
FastEmbed runs in the backend process. Gemini is a separate chat/extraction
provider. An external MCP host normally supplies its own conversational model.

## Isolation and revisions

Account keys and OAuth grants map to `user_id`. Two keys for the same account
intentionally share data. Two people need different account identities, not just
different conversations or tokens. See `USER_ISOLATION.md` for setup and tests.

MCP updates require an expected version. The server locks before comparing that
version and writing the next revision. A stale client receives a conflict rather
than silently overwriting a newer change. Deletion previews identify a candidate;
confirmed deletion targets an explicit ID and version.

## Verification and deployment boundaries

Unit tests cover input contracts and decision logic. Opt-in integration tests
exercise real database transactions in isolated schemas. Passing SDK discovery
does not prove a complete real-client OAuth or memory round trip.

Cloudflare forwards HTTPS to the backend; it does not host the Python application.
Neon persists data independently of the laptop. `/health` checks process liveness;
`/ready` checks database, vector extension, migrations, and TLS. Neither proves
that the LLM provider or embedding inference is available.

`sdk/`, `extensions/`, `benchmarks/`, and `evaluation/` contain clients and
evaluation tooling rather than the central request handler. Historical reports
are evidence snapshots, not current deployment configuration.
