# RecallFabric

RecallFabric is a shared persistent memory layer for AI assistants using MCP. ChatGPT and Claude retain their own native memories; RecallFabric provides shared, account-scoped memories across clients. It does not automatically copy entire conversations.

## 1. Already Set Up? Launch RecallFabric

For a Windows machine where the repo is cloned, `.venv` and dependencies exist, `.env` and Neon are configured, a RecallFabric account exists, and `cloudflared` is installed. Otherwise, start with [Section 2 — New Device? Full Installation](#2-new-device-full-installation).

### 1. Start backend

Keep an already running, healthy backend; otherwise run:

```powershell
cd "C:\Projects\New-Recall-Fabric\Capstone-RecallFabric-Complete"

.venv\Scripts\python.exe -m uvicorn recallfabric.main:create_app --factory --host 127.0.0.1 --port 8000 --workers 1 --proxy-headers --forwarded-allow-ips 127.0.0.1
```

Verify in a browser or another terminal:

```text
http://127.0.0.1:8000/health
http://127.0.0.1:8000/ready
```

`/health` should return 200, `status: ok`. `/ready` should return 200 with database reachable, pgvector enabled, migration head matching, and SSL in use. It does not test embedding inference; see [Full Installation](#e-configure-neon-and-prepare-fastembed) if the model is missing. Settings load `.env` from the working directory, not `.env.local`; process environment takes precedence.

### 2. Start Cloudflare Quick Tunnel

In a second terminal (keep an existing working tunnel instead of creating another):

```powershell
cloudflared tunnel --protocol http2 --url http://127.0.0.1:8000 --no-autoupdate
```

This generates a temporary hostname such as `https://example-name.trycloudflare.com`. **Keep the tunnel terminal running.** Restarting it normally changes the hostname. Laptop shutdown stops public access; Neon memories remain stored.

### 3. Update public origin

Open the ignored `.env` and replace both values with the actual tunnel origin:

```dotenv
RECALLFABRIC_MCP_PUBLIC_URL=https://example-name.trycloudflare.com
RECALLFABRIC_OAUTH_AUTHORIZATION_SERVER=https://example-name.trycloudflare.com
```

Use **no `/mcp` and no trailing slash**. These lines must be active, **not commented with `#`**. Restart **only the backend** using step 1. **Do not restart cloudflared.** If the configured origins already match a working connection, leave them unchanged.

<a id="13-verify-public-https-and-mcp"></a>

### 4. Verify public discovery

Check these URLs, replacing `<tunnel>` with the actual hostname:

```text
https://<tunnel>/.well-known/oauth-protected-resource/mcp
https://<tunnel>/.well-known/oauth-authorization-server
https://<tunnel>/ready
```

Expected: all return 200; `authorization_servers` contains the current tunnel origin, `issuer` equals that origin, and `/ready` is healthy. Resource metadata identifies the resource ending `/mcp`. An unauthenticated request to `https://<tunnel>/mcp/` should return a 401 challenge. **The account API key does not fix OAuth discovery problems**; correct the origin settings and reload the backend first.

### 5. Locate RecallFabric API key

Local file: **`C:\Projects\New-Recall-Fabric\.recallfabric-demo\account.json`**. Stored field: **`api_key`**. Never expose, share, or commit the value. The file is outside the repository; ignore rules also protect local account files. If absent, see [account provisioning/recovery](#f-provision-or-recover-the-recallfabric-account). The provisioning API returns `key`; the local recipe saves it as `api_key`.

### 6. Connect ChatGPT

**Plugins → + → Add custom MCP server**. Name: **RecallFabric**. URL: **`https://<tunnel>/mcp/`**. Use automatic OAuth registration. Review the connection warning, create the plugin, paste `api_key` on the RecallFabric consent page, approve, and select **Continue to your connected app** if shown. Return to ChatGPT, finish installation, and confirm tools are visible and enabled.

Account/workspace permissions apply; [official instructions](https://help.openai.com/en/articles/12584461-connecting-custom-mcp-servers-in-chatgpt) describe full custom read/write MCP support for Business and Enterprise/Edu. Older UIs may use Settings → Apps. For changed descriptions at the same URL, use **Plugins → RecallFabric → Refresh** where available and a fresh chat; reconnection is not normally required.

### 7. Connect Claude

**Customize → Connectors → Add custom connector**. Use **Web**, **Sign in now**, **Register automatically**, and **`https://<tunnel>/mcp/`**. Authorize with the **same RecallFabric account key as ChatGPT**; approve and complete continuation if shown. Confirm the connector is connected and enabled. Each client receives its own OAuth grant/tokens; do not share them.

[Claude Free supports one custom connector at a time](https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp). Workspace administrators may first need to add the connector for their organization.

### 8. Quick test

ChatGPT:

```text
Remember that Project Orion uses Spring Boot, React and PostgreSQL.
```

Claude, in a fresh enabled conversation:

```text
What do you know about Project Orion?
```

Expected: an actual RecallFabric call retrieves the memory created through ChatGPT. Check tool activity; an answer alone is not proof. Automatic invocation remains client-controlled. ChatGPT/Claude provide their own reasoning; **Ollama is not required for normal MCP memory usage**. FastEmbed provides semantic embeddings/retrieval.

> [!WARNING]
> **If the tunnel hostname changes**, repeat only:
>
> 1. Update the two `.env` public-origin variables.
> 2. Restart only the backend; keep the new tunnel running.
> 3. Verify OAuth metadata.
> 4. Reconnect/update ChatGPT as its UI requires.
> 5. Recreate/update the Claude connector (remove/re-add if required).
> 6. Reauthorize both using the same RecallFabric account.
>
> **Neon data remains unchanged.** Old resource-bound tokens do not apply to the new hostname.

## 2. New Device? Full Installation

For a completely new Windows machine. Complete A–H in order; backend launch and client connection commands live only in Section 1.

### A. Install prerequisites

Install prerequisites: **Git, Python 3.12 (managed by uv below), uv, and cloudflared**. Ollama is optional. Use Windows 10 22H2 or newer, PowerShell, Git, uv, and **Python 3.12** (the CI/Docker version; package requirement >=3.12). Allow disk/RAM for dependencies and FastEmbed. Optional local Ollama models need additional disk/RAM; a GPU is optional.

You need a Neon database supporting `vector`, its credentials, a ChatGPT account/workspace permitted to create custom read/write MCP connections, and a Claude account permitted to add a custom connector. No local PostgreSQL or Docker is needed for this Neon setup.

Install Git and uv if absent, then reopen PowerShell for PATH changes:

```powershell
winget install --id Git.Git --exact
winget install --id astral-sh.uv --exact
git --version
uv --version
```

See [uv installation](https://docs.astral.sh/uv/getting-started/installation/) for alternatives. Cloudflared installation is in part G; optional Ollama is in part H. Do not install replacements or start another tunnel on the working demo laptop.

### B. Clone repository

Choose another empty parent if this clone location exists:

```powershell
New-Item -ItemType Directory -Force C:\Projects\New-Recall-Fabric | Out-Null
Set-Location C:\Projects\New-Recall-Fabric
git clone --branch ready-for-mcp https://github.com/tusharsanka4/Capstone-RecallFabric.git Capstone-RecallFabric-Complete
Set-Location Capstone-RecallFabric-Complete
git branch --show-current
```

Run backend commands from `C:\Projects\New-Recall-Fabric\Capstone-RecallFabric-Complete`, including in each new terminal. A clone contains neither credentials nor the protected account file.

### C. Create Python environment/install dependencies

```powershell
uv python install 3.12
uv sync --locked --python 3.12
.venv\Scripts\python.exe --version
```

Use the explicit virtual-environment executable; activation and execution-policy changes are unnecessary. `uv.lock` pins dependencies. Do not copy `.venv` between devices.

<a id="configuration"></a>

### D. Configure `.env`

Create `.env` in the repository root; do not overwrite an existing file. Replace the admin-secret/database placeholders locally before starting. The example below deliberately uses ASCII encoding for Windows PowerShell compatibility and contains no real credentials.

```powershell
if (Test-Path -LiteralPath .env) { throw '.env exists; review without overwriting.' }
@'
RECALLFABRIC_ENVIRONMENT=production
RECALLFABRIC_AUTH_ENABLED=true
RECALLFABRIC_ALLOW_PUBLIC_SIGNUP=false
RECALLFABRIC_ADMIN_TOKEN=REPLACE_WITH_A_LONG_RANDOM_SECRET
RECALLFABRIC_DATABASE_URL=postgresql://USER:URL_ENCODED_PASSWORD@YOUR-ENDPOINT.neon.tech/neondb?sslmode=require
RECALLFABRIC_DB_SSLMODE=require
RECALLFABRIC_RUN_MIGRATIONS=false
RECALLFABRIC_WORKERS=1
RECALLFABRIC_MCP_PUBLIC_URL=https://replace-me.trycloudflare.com
RECALLFABRIC_OAUTH_AUTHORIZATION_SERVER=https://replace-me.trycloudflare.com
RECALLFABRIC_OAUTH_SCOPES=memory:read memory:write
RECALLFABRIC_LLM_PROVIDER=ollama
RECALLFABRIC_ALLOW_LOCAL_OLLAMA=true
RECALLFABRIC_EMBEDDING_PROVIDER=fastembed
RECALLFABRIC_EMBEDDING_MODEL=BAAI/bge-small-en-v1.5
RECALLFABRIC_MCP_JSON_RESPONSE=true
RECALLFABRIC_MCP_STATELESS_HTTP=true
'@ | Set-Content -LiteralPath .env -Encoding ascii
```

#### Required for this authenticated setup

- `RECALLFABRIC_DATABASE_URL`: the intended Neon PostgreSQL URL; URL-encode reserved password characters. It overrides separate DB connection fields.
- `RECALLFABRIC_DB_SSLMODE=require`: retain `sslmode=require` in the URL too.
- `RECALLFABRIC_ENVIRONMENT=production`, `RECALLFABRIC_AUTH_ENABLED=true`, `RECALLFABRIC_ALLOW_PUBLIC_SIGNUP=false`: keep authentication and administrator-controlled accounts.
- `RECALLFABRIC_ADMIN_TOKEN`: a long random admin secret, distinct from the account API key.
- `RECALLFABRIC_EMBEDDING_PROVIDER=fastembed`, `RECALLFABRIC_EMBEDDING_MODEL=BAAI/bge-small-en-v1.5`: explicit reproducible embedding configuration (384 dimensions); preserve compatibility with stored vectors.

Generate an admin secret with a password manager, or copy a captured value without displaying it:

```powershell
$adminToken = & .venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(48))"
Set-Clipboard -Value $adminToken
# Paste into RECALLFABRIC_ADMIN_TOKEN in the local .env editor; save.
Set-Clipboard -Value ''
```

#### Demo-only transport/public-origin configuration

- `RECALLFABRIC_MCP_PUBLIC_URL` and `RECALLFABRIC_OAUTH_AUTHORIZATION_SERVER`: placeholders until Section 1's tunnel step. Both must be the same real HTTPS **origin only**, without `/mcp` or a trailing slash; uncomment both lines.
- `RECALLFABRIC_MCP_JSON_RESPONSE=true`, `RECALLFABRIC_MCP_STATELESS_HTTP=true`: required by this Quick Tunnel recipe, which cannot use SSE.
- `RECALLFABRIC_LLM_PROVIDER=ollama`, `RECALLFABRIC_ALLOW_LOCAL_OLLAMA=true`: select a valid loopback backend-provider configuration under the current production validator, even when no backend LLM requests are made. These do **not** start or require an Ollama server for normal MCP usage. See optional settings in part H; hosted providers remain alternatives.

#### Optional settings

- `RECALLFABRIC_WORKERS=1`: default one; the launch command explicitly uses one worker.
- `RECALLFABRIC_RUN_MIGRATIONS=false`: default false; used by Docker entrypoint, not Uvicorn. Migrate explicitly only after confirming the target.
- `RECALLFABRIC_OAUTH_SCOPES=memory:read memory:write`: existing default; retain both for the demonstration.
- Local chat/extraction provider/model overrides are described in part H.

`.env` is loaded from the working directory; `.env.local` is not automatically loaded. Process environment takes precedence. The broad [.env.example](.env.example) is a settings reference, not another mandatory template. If using it as a base, clear its default `RECALLFABRIC_DB_PASSWORD` for a Neon URL; production rejects the local default password. No hosted LLM API key is needed for this configuration. Do not change relevance/entity settings during setup.

### E. Configure Neon and prepare FastEmbed

In Neon, select the intended project, branch, database, and role. Obtain the connection string from **Connect**, retain TLS, and save only in `.env`. Existing data requires the **same database branch and account identity**.

A fresh database needs `vector` and all migrations. The migration chain creates the extension; the role needs permission. See [Neon's pgvector guide](https://neon.com/docs/extensions/pgvector). No local PostgreSQL installation is needed.

Read-only revision checks:

```powershell
.venv\Scripts\python.exe -m alembic heads
.venv\Scripts\python.exe -m alembic current
```

Repository head: **`e1a2b3c4d501`**, the OAuth persistence migration. The existing demo database is already at head; **do not reinitialize it**. On a **new empty database only**, after confirming the target and authorization:

```powershell
.venv\Scripts\python.exe -m alembic upgrade head
```

For existing databases, review pending migrations and arrange a backup before an authorized upgrade. Never reset a database or delete volumes as a shortcut. Neon SQL can check `SELECT extversion FROM pg_extension WHERE extname='vector';`. Readiness below checks connectivity/vector/revision/TLS. Do not print the database URL.

After configuration and database checks, prepare FastEmbed once (first download needs internet):

```powershell
.venv\Scripts\python.exe -m recallfabric.embeddings --download
```

This verifies passage/query inference. `/ready` checks database/vector/migration/TLS, not embeddings.

<a id="provision-the-shared-account-and-protect-its-key"></a>

### F. Provision or recover the RecallFabric account

Start the backend using [Section 1, step 1](#1-start-backend) after completing D/E; no tunnel is needed for local administrator provisioning. Keep that backend running when returning to Section 1.

**Current file: `C:\Projects\New-Recall-Fabric\.recallfabric-demo\account.json`. The saved key field is `api_key`; other current fields are `user_id` and `origin`.** Never display, upload, or commit its real key.

The existing file was created by a local demo helper outside Git. Cloning does not regenerate it. The supported process is administrator-protected **`POST /v1/auth/keys`**. Its response field is **`key`**; the recipe saves it as **`api_key`**. The endpoint itself does not create a local file.

- **Reuse existing memories:** securely transfer the account file, or have the administrator issue another key for the exact existing `user_id`. Do not invent another ID. This recipe refuses to overwrite a file.
- **New isolated account:** generate a new ID below; it starts empty. The namespace belongs to API keys; there is no separate user row to pre-create. Only an authenticated administrator may choose it.

In another terminal, enter the repository directory and read the same admin secret configured in `.env`:

```powershell
$adminSecret = Read-Host 'RecallFabric admin token from your local .env' -AsSecureString
$adminToken = [System.Net.NetworkCredential]::new('', $adminSecret).Password
$accountDir = Join-Path (Split-Path -Parent $PWD.Path) '.recallfabric-demo'
$accountPath = Join-Path $accountDir 'account.json'
if (Test-Path -LiteralPath $accountPath) { throw 'Account exists; reuse, do not overwrite.' }
New-Item -ItemType Directory -Force $accountDir | Out-Null
$identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
icacls $accountDir /inheritance:r /grant:r "${identity}:(OI)(CI)F"
if ($LASTEXITCODE -ne 0) { throw 'Failed to protect account directory.' }

# NEW account only. For existing data, use its exact existing user_id instead.
$userId = 'rf_user_' + [guid]::NewGuid().ToString('N')
$payload = @{user_id=$userId; name='shared-mcp-account'} | ConvertTo-Json
$issued = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/v1/auth/keys -Headers @{'X-Admin-Token'=$adminToken} -ContentType application/json -Body $payload
@{user_id=$issued.user_id; api_key=$issued.key} | ConvertTo-Json | Set-Content -LiteralPath $accountPath -Encoding utf8
Remove-Variable issued, adminToken, adminSecret
```

Fresh files need `user_id` and `api_key`; `origin` is optional diagnostic data. The ACL must succeed **before** writing. With this layout the file is exactly `C:\Projects\New-Recall-Fabric\.recallfabric-demo\account.json`, outside Git. Back it up securely: only a hash is stored server-side, so the original plaintext key cannot be recovered from Neon.

Copy without printing:

```powershell
$account = Get-Content -Raw -LiteralPath $accountPath | ConvertFrom-Json
Set-Clipboard -Value $account.api_key
# Paste only into RecallFabric's HTTPS OAuth consent page, then clear:
Set-Clipboard -Value ''
Remove-Variable account
```

Both clients must authorize against this **same RecallFabric account**, receiving separate OAuth access/refresh tokens. Do not give either client the admin token, Neon password, or the other client's tokens. Different IDs mean different memories, even on the same database.

### G. Install Cloudflare tunnel tooling

Use [official Cloudflare Windows downloads](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/downloads/) (64-bit MSI/executable), or the Windows package:

```powershell
winget install --id Cloudflare.cloudflared --exact
```

Reopen PowerShell and verify:

```powershell
cloudflared --version
```

If PATH has not updated, reopen the terminal. The demo's installed executable is `C:\Program Files (x86)\cloudflared\cloudflared.exe`; invoke a quoted path with PowerShell's `&` operator.

Start the tunnel only with [Section 1, step 2](#2-start-cloudflare-quick-tunnel); do not create a second tunnel on an already connected machine.

### H. Optional Ollama setup

```text
ChatGPT or Claude -> their own LLM -> RecallFabric MCP tools -> FastEmbed -> Neon + pgvector
```

A running Ollama server is not required for normal `remember` (`extract=false`), `recall`, `list_memories`, `update_memory`, `forget`, or cross-client MCP continuity. ChatGPT and Claude perform their own reasoning and select tools. FastEmbed remains required for semantic embeddings/retrieval unless another embedding provider is explicitly configured; existing stored vectors must remain compatible.

Ollama support remains available for local RecallFabric `/chat`, extraction workflows, development/testing, and standalone operation where the MCP host is not supplying the reasoning. The current optional local model is `qwen2.5:3b-instruct`.

**Existing implementation boundary:** `remember(extract=true)` invokes the configured extraction LLM. Ordinary `remember` may also invoke that provider to classify an ambiguous conflict with an existing memory; provider failure skips that conflict check rather than preventing storage. It may add latency and does not guarantee automatic supersession. For reliable changed-state updates without a backend LLM, the client should recall the current record and call `update_memory` with its ID and `expected_version`. These paths are documented as implemented; no production behavior is changed here.

Install [Ollama for Windows](https://docs.ollama.com/windows) using its [official installer](https://ollama.com/download/windows). Reopen PowerShell:

```powershell
ollama --version
ollama pull qwen2.5:3b-instruct
```

The Windows app normally runs the API in the background. If not running, leave this command running in another terminal:

```powershell
ollama serve
```

Do not start another instance if Ollama already owns port 11434. Verify the model and generation:

```powershell
(Invoke-RestMethod http://127.0.0.1:11434/api/tags).models.name
$body = @{model='qwen2.5:3b-instruct'; prompt='Reply with OK.'; stream=$false} | ConvertTo-Json
(Invoke-RestMethod -Method Post -Uri http://127.0.0.1:11434/api/generate -ContentType application/json -Body $body).response
```

The working model is [`qwen2.5:3b-instruct`](https://ollama.com/library/qwen2.5:3b-instruct). Ollama handles extraction, conflict decisions, and optional backend chat. **FastEmbed remains the embedding provider**; do not switch embeddings to Ollama. Local-production Ollama uses the explicit loopback opt-in in part D.

If enabling those optional local workflows, set these overrides in the existing ignored `.env` (the provider selector/production opt-in are already in part D):

```dotenv
RECALLFABRIC_CHAT_PROVIDER=ollama
RECALLFABRIC_EXTRACTION_PROVIDER=ollama
RECALLFABRIC_LLM_BASE_URL=http://127.0.0.1:11434/v1
RECALLFABRIC_CHAT_MODEL=qwen2.5:3b-instruct
RECALLFABRIC_EXTRACTION_MODEL=qwen2.5:3b-instruct
```

### I. Finish setup

> Once installation is complete, return to **[Section 1 — Already Set Up? Launch RecallFabric](#1-already-set-up-launch-recallfabric)**.

## Architecture overview

```mermaid
flowchart TD
    A[ChatGPT] --> T[Cloudflare Tunnel / HTTPS]
    B[Claude] --> T
    C[Other MCP client] --> T
    T --> R[RecallFabric FastAPI + MCP]
    R --> E[FastEmbed: local embeddings]
    E --> N[(Neon PostgreSQL + pgvector)]
    R --> N
    R -.-> O[Optional Ollama: local chat / extraction / conflicts]
```

Cloudflare only exposes the locally running backend publicly. Python and FastEmbed run on the laptop; Ollama runs only for optional local-LLM workflows; Neon holds durable data. Quick Tunnel uses stateless MCP HTTP with JSON responses because it does not support SSE. This is a demo/development setup without an uptime guarantee.

## Features

- MCP Streamable HTTP, ChatGPT custom MCP support, and Claude custom connectors.
- Shared account-scoped memory, tenant isolation, FastEmbed, and pgvector.
- Semantic recall, relevance filtering, entity/project-aware recall, and memory supersession.
- Assistant-recommendation acceptance, automatic recall guidance, and conservative durable-memory guidance.
- OAuth authorization-code flow with PKCE S256, resource/audience binding, scopes, and independent client grants.
- Memory history and provenance.

Core tools: `recall`, `remember`, `update_memory`, `forget`, `list_memories`, `get_profile`, `get_memory_history`, `get_provenance`. Legacy aliases remain available. The client model controls invocation; automatic recall/write is not guaranteed.

### Durable memory behavior

Natural durable statements such as “My secondary monitor is vertical for coding” or “Nova now uses Django” qualify without “remember this.” Temporary feelings, tentative plans, hypotheticals, quotations, general knowledge, and unaccepted assistant recommendations do not. Routine save narration is discouraged.

MCP receives tool calls, not ordinary conversation messages. Clients decide what to save. Use recall plus versioned update_memory for changed state, rather than introducing contradictory active memories. Current user corrections take precedence over older memory.

## Development and testing

Focused checks, without benchmarks or hosted migrations:

```powershell
.venv\Scripts\python.exe -m pytest tests/test_auto_write_guidance.py tests/test_mcp_guidance.py tests/test_conversation_decisions.py tests/test_mcp_contracts.py tests/test_recall_relevance.py tests/test_entity_memory.py tests/test_oauth_consent_proxy.py tests/test_public_mcp_security.py -q -p no:cacheprovider
.venv\Scripts\ruff.exe check .
.venv\Scripts\python.exe scripts/generate_tool_schemas.py --check
git diff --check
```

### Authenticated MCP discovery probe

Verify authenticated discovery without writing memories, from the repository directory:

```powershell
$accountPath = Join-Path (Split-Path -Parent $PWD.Path) '.recallfabric-demo\account.json'
$env:RECALLFABRIC_API_KEY = (Get-Content -Raw -LiteralPath $accountPath | ConvertFrom-Json).api_key
try {
    .venv\Scripts\python.exe scripts/mcp_probe.py --url "$publicOrigin/mcp/"
} finally {
    Remove-Item Env:\RECALLFABRIC_API_KEY -ErrorAction SilentlyContinue
}
```

The probe checks initialization, eight core tools (11 total with aliases), resources, and prompts. It does not write memories, test OAuth code exchange, or prove a real client connection. Complete those flows next.

## Troubleshooting

### CSP OAuth continuation issue

Consent posts to relative same-origin `/auth/oauth/authorize/approve`, preserving `Content-Security-Policy: form-action 'self'`. Approval returns a same-origin **200 continuation page** with navigation/link to the registered callback, avoiding a cross-origin form-POST redirect chain. Let it continue or click its link. Check public-origin/proxy HTTPS metadata; never relax CSP with wildcards.

### 400 `access_denied` after failed authorization

Transactions are one-use and expire. Consumed/expired requests cannot be reused from an old consent tab. Start a **fresh authorization from the client**. If it persists, check key validity/required fields; never bypass CSRF or reuse a code.

### Irrelevant or missing memories

`limit` is a maximum, not a required count. Relevance filtering may return zero. Entity-aware recall separates named projects and permits comparisons. See [relevance semantics](docs/RECALL_RELEVANCE.md) and [entity matching](docs/ENTITY_MEMORY.md). Do not lower the working threshold or change embeddings as an initial fix.

### Clients do not automatically recall/write

Enable RecallFabric, refresh metadata where supported, and start a fresh chat. Inspect actual tool activity. Client models decide invocation; not all clients automatically load `use_memory`. General knowledge, temporary, and speculative statements should not trigger writes. See [guidance](docs/MCP_TOOL_GUIDANCE.md).

### Backend works locally but not publicly / tunnel changed

Check the existing cloudflared process, printed URL, local port 8000, public `/ready`, and both discovery paths. Keep the original tunnel alive. Check outbound access and avoid interactive Cloudflare gates. A 401 on unauthenticated MCP is correct; 503 readiness requires DB/vector/revision/TLS investigation. Process environment overrides `.env`. For a changed hostname, follow [restart behavior](#restart-behavior), not just a client URL edit.

### Blank provider/model/database errors

Verify FastEmbed's cache is accessible, Neon points to the intended branch, and migrations match head. Only for optional local chat/extraction or backend conflict classification, check that Ollama lists `qwen2.5:3b-instruct` and is running. Normal client-driven MCP usage does not need an Ollama start. Never print connection strings or carry default local database passwords into production.

### Restart behavior

**Backend restart:** stop/restart only Uvicorn. Keeping cloudflared alive preserves the URL and existing grants. Check readiness/discovery afterward. Metadata refresh may be needed; reconnection/reauthorization is not normally necessary at the same origin.

**Cloudflared restart:** Quick Tunnel hostnames change. Then:

1. Capture the new HTTPS origin.
2. Update both public-origin settings.
3. Restart only the backend and verify readiness/discovery.
4. Update/recreate ChatGPT's connection and Claude's connector as required.
5. Start fresh OAuth flows for both, using the same account key.

Old resource-bound tokens are not valid for the new hostname. Never rewrite audiences or weaken validation.

**Laptop shutdown:** service becomes unavailable; Neon memories remain stored. Start the backend and a new tunnel after boot, then follow the hostname-change procedure. Start Ollama only if using optional server-side LLM workflows. Prevent sleep during the demo. Stable hostnames require a separately configured named tunnel/domain; this guide purchases nothing.

## Security

- Never commit `.env`, `.env.local`, account/session files, API keys, OAuth tokens, Neon credentials, or Cloudflare credentials. Review staged changes even with `.gitignore` protection.
- Keep `account.json` outside Git with restrictive permissions; copy keys only into the correct HTTPS consent page and clear the clipboard.
- Signup stays disabled, auth enabled, and scopes intact. The admin token is not a client account key.
- Same account for continuity, independent client OAuth grants. Never share access/refresh tokens between clients.
- Tunnel only the backend, never PostgreSQL/Ollama ports. Use synthetic data; do not reset databases or overwrite real memories to repair setup.

## Project structure and additional docs

```text
src/recallfabric/   FastAPI, MCP, auth, memory services, providers, embeddings
migrations/        Alembic schema history
tests/             Focused and opt-in integration tests
scripts/           MCP probe and development utilities
docs/              Specialist workflows and historical verification records
sdk/               Python and JavaScript clients
extensions/        Optional browser integration
benchmarks/        Memory accuracy datasets and tooling
evaluation/        Capstone evaluation evidence
```

- [MCP contract, stdio, and lifecycle checks](docs/MCP_SERVER_SETUP.md)
- [OAuth architecture](docs/UNIVERSAL_AI_MEMORY_CONNECTOR.md)
- [IDE and legacy bridge configurations](docs/connecting/README.md)
- [Cloud alternatives](docs/deployment.md) and [Render environment reference](deploy.render.env.example)
- [Zero-cost verification record](docs/ZERO_COST_MCP.md)
- [Python SDK](sdk/python/README.md) and [JavaScript SDK](sdk/js/README.md)
- [Security reference](docs/security.md)

Historical capstone reports/evaluation artifacts are retained as snapshots, not instructions to replace a working deployment.

### Verification scope

Commands and paths were checked against the repository, PowerShell syntax, environment validation, and official client documentation. This documentation-only update does not start/restart services, create a tunnel, modify origins, run migrations, or claim a new live client connection. Earlier public verification is historical evidence, not a promise that a temporary hostname remains available. Follow Section 1 to verify your own installation.
