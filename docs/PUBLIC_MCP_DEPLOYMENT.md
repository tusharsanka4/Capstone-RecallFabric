# Public MCP deployment handoff

Prepared 2026-11-19. No deployment or hosted database migration was performed.

## Security changes

Signup rejects supplied user IDs and generates a random server-owned identity. Repeated
registrations create distinct tenants; they never issue credentials for an existing tenant.
Existing account ownership is established by possession of its active API key in the OAuth
consent flow; admin-protected issuance is the recovery/provisioning mechanism. Public signup
is disabled in the Render template. No password/email identity system was introduced.

Consent names are HTML-escaped with a restrictive content security policy. OAuth requests
must supply the advertised resource, which is persisted on authorization requests, codes,
access tokens and refresh tokens. Token exchange, refresh and MCP verification reject a
mismatching resource. Legacy unbound OAuth grants must reconnect after migration; API keys
and memories are preserved. Code/refresh consumption uses row locks and refresh rotation
retains its family ID. OAuth errors use standard top-level fields. Redirects reject non-loopback
HTTP, credentials and fragments, and retain preexisting callback query parameters.

Blank optional provider overrides now resolve to the configured default provider. Production
OAuth URLs, when provided, must be HTTPS origins; the built-in issuer must use the same origin.

## Hosted state verified read-only

The current environment now supplies a Neon URL and a hosted-provider key. A read-only
connection confirmed TLS, pgvector 0.8.7 and Alembic revision da7c42e6f901. Credentials were
not printed. New migration e1a2b3c4d501 is NOT applied. Do not run hosted MCP with this code
against the old OAuth schema. Obtain explicit approval before applying the additive migration.
It adds nullable resource columns only, with no memory-table changes or legacy-token backfill.
Unbound legacy grants fail closed and must reauthorize.

The current environment differs from the earlier audit; neither .env nor .env.local was edited.
Use deploy.render.env.example for safe placeholder configuration. Settings reads .env and process
variables, not .env.local automatically. Do not replace an existing encryption key.

## Render and Docker

Existing Dockerfile installs locked dependencies and bakes FastEmbed at build time.
The entrypoint binds 0.0.0.0 and Render PORT and starts the FastAPI factory. Blueprint now
uses the 2 GB Standard plan, one worker, /ready health checks, signup disabled, explicit public
URLs, preserved encryption configuration and startup migrations disabled. /health remains
liveness only. MCP is Streamable HTTP at /mcp/; discovery advertises the resource ending /mcp.
Set the public URL to an origin, without /mcp. Keep one instance and worker because sessions
and rate limits remain process-local; clients must reconnect after restarts.

A local Windows FastEmbed probe produced 384 dimensions with 248.3 MB peak working set.
This supports a 2 GB starting allocation but does not establish container/Linux peak memory
under concurrent load. Test the full image under the intended memory limit before presenting.
Docker CLI is installed but the Linux daemon is unavailable; image build remains unverified.
No local Ollama is required: configure a supported hosted LLM, preserving FastEmbed identity.
Direct remember still constructs the conflict-resolution LLM provider. Recall uses embeddings
and the database. Preserve the existing database embedding model/dimensions; switching them
can hide existing memories from semantic retrieval. No extraction prompts/logic were changed.

Startup:

```sh
uvicorn recallfabric.main:create_app --factory --host 0.0.0.0 --port "$PORT" --workers 1
```

## Required configuration names

PORT, RECALLFABRIC_ENVIRONMENT, RECALLFABRIC_AUTH_ENABLED,
RECALLFABRIC_ALLOW_PUBLIC_SIGNUP, RECALLFABRIC_ADMIN_TOKEN,
RECALLFABRIC_DATABASE_URL, RECALLFABRIC_DB_SSLMODE,
RECALLFABRIC_RUN_MIGRATIONS, RECALLFABRIC_WORKERS,
RECALLFABRIC_MCP_PUBLIC_URL, RECALLFABRIC_OAUTH_AUTHORIZATION_SERVER,
RECALLFABRIC_OAUTH_SCOPES, RECALLFABRIC_LLM_PROVIDER,
RECALLFABRIC_CHAT_PROVIDER, RECALLFABRIC_EXTRACTION_PROVIDER,
RECALLFABRIC_OPENAI_API_KEY, RECALLFABRIC_OPENAI_MODEL,
RECALLFABRIC_EMBEDDING_PROVIDER, RECALLFABRIC_EMBEDDING_MODEL,
RECALLFABRIC_EMBEDDING_CACHE_DIR. Use the corresponding provider key/model names if choosing
Gemini or Anthropic. RECALLFABRIC_ENCRYPTION_KEY is conditional on existing encrypted data.

## Approval and execution order

1. Review the pending merge and security diff. Approve commit/push separately; neither was done.
2. Approve and rehearse the migration on a disposable PostgreSQL database, then approve its
   application to Neon. Do not run mutation tests against the existing hosted account.
3. Start Docker Desktop Linux daemon and build the image. Verify baked embeddings under 2 GB.
4. Supply final Render HTTPS origin, preserve the account encryption key if any, and verify
   provider model access. Credentials are present locally but hosted operation is not proven.
5. Only with deployment approval: create the one-instance Render Docker service, populate
   secrets and final public origin, and check /health, /ready and protected /mcp/ over HTTPS.
6. Use Inspector for HTTP initialize, tools/list and tools/call. Configure ChatGPT and Claude
   through OAuth/DCR. Copy each host's exact current callback URI; no authentication bypass.
7. Approve both grants with the same existing account key. Run ChatGPT remember -> Claude
   recall -> Claude versioned update -> ChatGPT recall. Verify persistence and wrong-account
   isolation. Full PostgreSQL-backed roundtrip and live-client compatibility remain acceptance gates.

Tests use mocked isolated account data for authenticated HTTP tool execution; that does not
prove actual Neon memory writes or PostgreSQL row-lock behavior. Opt-in database/model tests
remain disabled. No database contents or Docker volumes were reset or deleted.

## Verification results

- Complete suite: 221 passed, 104 skipped, 0 failed (database/model opt-ins disabled).
- Focused auth/OAuth/MCP security suite: 49 passed, 5 skipped, 0 failed.
- Ruff repository check: all checks passed.
- Official SDK stdio probe: initialize, tools/list, resources/list and prompt retrieval passed;
  negotiated protocol 2025-11-25. HTTP tests cover authenticated initialization, discovery and
  tool execution against isolated mocked data, and rejection of invalid/wrong-audience tokens.
- Local real FastEmbed: 384-dimensional output, 248.3 MB peak Windows working set.
- Neon: read-only TLS/vector/revision verification passed; no hosted mutations performed.
- Docker image build: blocked, Linux daemon not running. Hosted client roundtrip not attempted.
- Alembic source head: e1a2b3c4d501; hosted revision remains da7c42e6f901.

Git remains ready-for-mcp at a92f77ef3e329a0612128a1fa78c3e1a3d3763f3 with
MERGE_HEAD 27f59fb65d4ea37c0269acb916540bec0a76000b. Original staged TLS change/test
are intact; new fixes are unstaged. No benchmark files/results, env files, memories, commits,
remote branches or Docker volumes were modified by this work.
