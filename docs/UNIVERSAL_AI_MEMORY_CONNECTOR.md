# Universal AI Memory Connector

RecallFabric is a tenant-scoped memory service. ChatGPT, Claude, and other MCP
clients supply their own model and conversation context; RecallFabric stores,
embeds, retrieves, versions, and deletes memories. RecallFabric therefore does
not require OpenAI or Anthropic model keys for MCP usage.

## Architecture

Clients connect to the Streamable HTTP MCP endpoint:

```text
AI client -> HTTPS reverse proxy -> RecallFabric /mcp -> PostgreSQL + embeddings
```

The authenticated principal, not a tool argument or an identity header, selects
the `user_id` used by every memory operation. The MCP tools are:

* `remember`
* `recall`
* `update_memory`
* `forget`
* `list_memories`
* `get_provenance`
* `get_memory_history`
* `get_profile`

## Authentication

The locally implemented remote-MCP authentication mechanism is a hashed,
revocable RecallFabric API key sent as `Authorization: Bearer <key>` (or
`X-API-Key`). API keys are never returned by API responses or logged. Production
mode requires authentication and rejects missing, invalid, and revoked keys.
The same key may be configured in multiple client connections to access one
RecallFabric account; keys belonging to different users cannot cross tenant
boundaries.

The service is also a public OAuth authorization server for MCP clients. It
publishes RFC 9728 protected-resource metadata (including the path-aware
`/.well-known/oauth-protected-resource/mcp`) and RFC 8414 authorization-server
metadata. It supports public-client registration, Authorization Code + PKCE
S256, exact callback matching, CSRF-bound consent, one-time five-minute codes,
hashed one-hour access tokens, refresh-token rotation with family revocation on
reuse, and token revocation.

The authorization page deliberately does **not** accept a user ID. The user
proves ownership of an existing RecallFabric account by entering an existing
RecallFabric API key; the key is checked against its hash and its stored account
ID becomes the grant subject. Thus ChatGPT and Claude can separately authorize
with keys belonging to the same account and share only that account's memories.
The key is never stored in the authorization transaction or returned to either
client. For a consumer-facing deployment, replace this key-entry login with a
real OIDC login/verified subject adapter; external JWT/OIDC validation is not
implemented in this repository.

## Local setup

```powershell
Set-Location C:\Projects\New-Recall-Fabric\Capstone-RecallFabric-Complete
$env:RECALLFABRIC_AUTH_ENABLED = "true"
$env:RECALLFABRIC_MCP_TRANSPORT = "streamable-http"
$env:RECALLFABRIC_MCP_PUBLIC_URL = "https://memory.example.com"
docker compose -p recallfabric-complete -f compose.yaml -f compose.complete.yaml up -d api
```

Create a key through the authenticated administration flow, then configure the
client with the resulting secret. Never put the key in source control or a
browser bundle.

## ChatGPT and Claude

Prerequisites for either host: deploy a public HTTPS URL, set
`RECALLFABRIC_MCP_PUBLIC_URL` to its origin, set authentication on, apply
Alembic head, and create an API key for the intended RecallFabric account.
Never use a LAN, HTTP, or tunnel URL for a production connector.

For ChatGPT Business or Enterprise/Edu, an eligible workspace admin creates a
custom MCP server, supplies `https://<host>/mcp`, selects OAuth, and completes
the RecallFabric consent page using that account's key. Request
`memory:read memory:write offline_access`; ChatGPT needs `offline_access` to
refresh a durable connection. Repeat the same process for Claude, again using
an API key owned by the same RecallFabric account. The two independently issued
OAuth tokens resolve to the same account without either MCP tool receiving a
user identifier.

Claude's exact connector UI/availability is account and plan dependent. Add the
same public `/mcp` URL as a custom connector, allow OAuth discovery, and approve
the same scopes and same RecallFabric account on its consent page. If the host
requires pre-registered redirect URIs rather than dynamic registration, register
that one HTTPS callback through `POST /auth/oauth/register` before starting the
connection.

ChatGPT and Claude have different product availability and connector
requirements. This repository contains no live ChatGPT or Claude installation,
so neither integration is claimed as connected.

## Deployment requirements

* Terminate TLS at a managed reverse proxy; do not expose the development
  server directly.
* Set `RECALLFABRIC_ENVIRONMENT=production`, a non-default database password,
  encryption key, admin token, and `RECALLFABRIC_AUTH_ENABLED=true`.
* Restrict CORS and proxy upstreams, configure rate limits, and keep secrets in
  a secret manager.
* Run Alembic migrations during deployment, back up PostgreSQL, and monitor
  `/health`, `/ready`, authentication failures, and database capacity.
* Set a canonical public URL; discovery metadata and the `resource` value must
  match it exactly. Configure DNS, TLS renewal, HSTS, proxy request-size limits,
  rate limits, and trusted forwarded headers.
* Back up and periodically restore-test PostgreSQL (including OAuth token and
  audit tables), retain authentication/audit logs, and monitor `/health`,
  `/ready`, 401/429 rates, token-rotation reuse, and database capacity.

## Troubleshooting

* `401`: the bearer key is missing, invalid, or revoked.
* `403`: the key belongs to a different account than the requested resource.
* `429`: the configured per-client rate limit was exceeded.
* `503`: the database or embedding provider is unavailable.
* Discovery reports no authorization server until
  `RECALLFABRIC_OAUTH_AUTHORIZATION_SERVER` is configured.

## Acceptance status

Implemented and locally tested: PKCE/OAuth lifecycle, refresh rotation and
revocation, account linking through API-key account proof, tenant-scoped MCP
tools, and PostgreSQL migration head `da7c42e6f901`. The local API and database
are ready to place behind a correctly configured HTTPS reverse proxy. ChatGPT
and Claude have not been connected in this environment, and this is not a
production-security certification. A future public deployment must replace the
local API-key approval page with verified OIDC identity mapping.
