# RecallFabric

RecallFabric is a shared persistent memory layer for AI assistants using MCP. ChatGPT and Claude retain their own native memories; RecallFabric provides shared, account-scoped memories across clients. It does not automatically copy entire conversations.

## QUICK START: Connect RecallFabric to ChatGPT and Claude

Assumes Windows, a cloned repository, installed Python dependencies, configured Neon/TLS and migrations, production authentication settings, and a downloaded FastEmbed model. If anything is missing, follow [full fresh-device installation](#full-fresh-device-installation), [configuration](#configuration), and [account provisioning](#provision-the-shared-account-and-protect-its-key) below. ChatGPT/Claude supply their own LLM reasoning and invoke memory tools; **a running Ollama server is not required for normal MCP memory usage**. See the [optional local-LLM boundaries](#ollama-is-optional-for-mcp-usage).

### Step 1 — Start the RecallFabric backend

In PowerShell, from the repository directory:

```powershell
Set-Location C:\Projects\New-Recall-Fabric\Capstone-RecallFabric-Complete
.venv\Scripts\python.exe -m uvicorn recallfabric.main:create_app --factory --host 127.0.0.1 --port 8000 --workers 1 --proxy-headers --forwarded-allow-ips 127.0.0.1
```

Settings load **`.env` from the working directory**; `.env.local` is not automatically loaded. Process environment overrides `.env`. Before exposing the server, confirm production mode, authentication enabled, public signup disabled, and JSON/stateless MCP enabled as in the configuration example. Use one worker. Do not start another backend if one already owns port 8000.

In another terminal:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
Invoke-RestMethod http://127.0.0.1:8000/ready
```

`/health` means the process is alive (200, `status: ok`). `/ready` means DB connectivity, pgvector, migration head, and configured TLS pass (200); it **does not run an embedding inference check**. Prepare/test FastEmbed separately with `.venv\Scripts\python.exe -m recallfabric.embeddings --download`. Resolve readiness 503s before connecting clients.

### Step 2 — Start one Cloudflare Quick Tunnel

If needed, install [cloudflared for Windows](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/downloads/) and reopen PowerShell:

```powershell
winget install --id Cloudflare.cloudflared --exact
cloudflared --version
```

If an existing tunnel is working, keep it and use its existing URL. Otherwise, in a dedicated terminal:

```powershell
cloudflared tunnel --protocol http2 --url http://127.0.0.1:8000 --no-autoupdate
```

Cloudflare prints an HTTPS origin like `https://example-random-name.trycloudflare.com`. Keep this terminal running. Do not restart `cloudflared` unnecessarily: each new Quick Tunnel normally gets a new hostname. Laptop shutdown stops public access, but memories remain stored in Neon. This demonstration uses stateless MCP HTTP with JSON responses; Quick Tunnel does not support SSE. See [official Quick Tunnel limits](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/).

### Step 3 — Configure the public MCP/OAuth origin

Edit only these settings in the ignored `.env`, substituting the actual URL printed by your tunnel:

```dotenv
RECALLFABRIC_MCP_PUBLIC_URL=https://example-random-name.trycloudflare.com
RECALLFABRIC_OAUTH_AUTHORIZATION_SERVER=https://example-random-name.trycloudflare.com
```

Both values are **origin only: no `/mcp`, other path, or trailing slash**. The client endpoint separately ends `/mcp/`. Keep authentication enabled, public signup disabled, and both MCP JSON/stateless settings true as shown in [configuration](#configuration).

Stop **only the backend** with Ctrl+C, then rerun step 1's Uvicorn command. **Do not restart cloudflared.** If both origins already match a working connection, do not change them or restart anything just to follow this guide.

<a id="13-verify-public-https-and-mcp"></a>

### Step 4 — Verify the public endpoint

In your administrative terminal:

```powershell
$publicOrigin = 'https://YOUR-ACTUAL-NAME.trycloudflare.com'
Invoke-RestMethod "$publicOrigin/health"
Invoke-RestMethod "$publicOrigin/ready"
Invoke-RestMethod "$publicOrigin/.well-known/oauth-protected-resource/mcp"
Invoke-RestMethod "$publicOrigin/.well-known/oauth-authorization-server"
curl.exe -sS -o NUL -w '%{http_code}' "$publicOrigin/mcp/"
```

Health/readiness/discovery should return 200. Metadata must advertise the actual HTTPS origin, protected resource `$publicOrigin/mcp`, authorization/token/registration endpoints, and PKCE S256. An unauthenticated **401 authorization challenge** from `/mcp/` is expected. Do not disable authentication to make it return 200.

### Step 5 — Locate the RecallFabric account key

Current local demo file: **`C:\Projects\New-Recall-Fabric\.recallfabric-demo\account.json`**. It is outside the repository; ignore rules also protect similarly named local account files. Never commit or share it. The stored key field is **`api_key`**. The administrator provisioning API returns **`key`**, which the local provisioning recipe saves as **`api_key`**.

Copy without displaying the value:

```powershell
$accountPath = 'C:\Projects\New-Recall-Fabric\.recallfabric-demo\account.json'
Set-Clipboard -Value ((Get-Content -Raw -LiteralPath $accountPath | ConvertFrom-Json).api_key)
# Paste only into the correct RecallFabric HTTPS consent page; clear afterward:
Set-Clipboard -Value ''
```

Both clients must authenticate against the **same RecallFabric account**, receiving **separate OAuth grants/tokens**. Never share OAuth access/refresh tokens between clients. If the file is absent, follow [fresh-account provisioning or existing-account recovery](#provision-the-shared-account-and-protect-its-key), not public signup. A clone does not recreate this file.

### Step 6 — Connect ChatGPT

Use [current official setup](https://help.openai.com/en/articles/12584461-connecting-custom-mcp-servers-in-chatgpt): **ChatGPT > Plugins > + > Add custom MCP server** (sometimes labeled Add MCP server). Account/workspace permission is required; full custom read/write MCP support is documented for Business and Enterprise/Edu. Older UIs may expose the equivalent under Settings > Apps.

1. Name **RecallFabric**; connection URL **`https://<tunnel-host>/mcp/`**. Select OAuth/automatic registration.
2. Review the risk warning, create/start the connection, and open OAuth consent.
3. Paste the RecallFabric account **API key**, then approve.
4. If shown, click **Continue to your connected app**.
5. Return to ChatGPT; finish installation and confirm tools such as `remember`, `recall`, `list_memories`, and `update_memory` are visible. Enable/select RecallFabric in the conversation; approve writes when prompted.

For description changes at the **same URL**, use **Plugins > RecallFabric > Refresh** where available, then a fresh chat. Reconnection is not normally needed.

Test: **“Remember that Project Orion uses Spring Boot, React and PostgreSQL.”** Verify an actual `remember` call. In a fresh enabled chat: **“Let's continue Project Orion.”** Expected: ChatGPT recalls relevant context automatically when appropriate. Model-controlled invocation is not guaranteed; inspect tool activity rather than trusting the answer alone.

### Step 7 — Connect Claude

Use [Claude's current connector setup](https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp): **Claude > Customize > Connectors > Add custom connector** (the add button may be **+ Add**).

1. Name **RecallFabric**, type **Web** if requested, URL **`https://<tunnel-host>/mcp/`**.
2. Authentication: **Sign in now**; OAuth client: **Register automatically**. Workspace administrators may first need to add the connector in organization settings.
3. Start OAuth and paste the **same RecallFabric account API key used for ChatGPT**. Approve.
4. Complete the continuation flow if shown, return to Claude, and confirm the connector is connected and enabled for the conversation.

Claude Free supports **one custom connector at a time**. If the URL changes, remove the old connector, add it with the new endpoint, and reauthorize. A backend-only restart at the same URL does not require that.

Test: **“What do you know about Project Orion?”** Expected: a real RecallFabric call retrieves the memory originally stored through ChatGPT.

### Step 8 — Prove cross-client memory

Use isolated synthetic project data and fresh conversations with RecallFabric enabled:

1. **ChatGPT:** “Remember that Project Helios is an AI-assisted developer dashboard using React, Spring Boot and PostgreSQL.” Verify successful `remember`.
2. **Claude:** “Let's continue Project Helios.” Verify `recall` retrieves the same project.
3. **Claude:** “Project Helios now uses FastAPI instead of Spring Boot.” Verify it recalls the current record and calls `update_memory` with its ID and `expected_version`. If not automatic, explicitly request the update.
4. **ChatGPT:** “What backend does Project Helios use now?” Verify current memory says **FastAPI**; Spring Boot is superseded, while React/PostgreSQL remain unchanged. History may show the old revision.

This proves shared durable memory, cross-client continuity, independent OAuth grants, and common Neon-backed account state. ChatGPT/Claude supply their own reasoning; ordinary memory tools use FastEmbed and Neon rather than requiring Ollama. A plausible answer without actual tool calls does not prove the round trip.

### If the tunnel URL changes

Quick Tunnel addresses are temporary. Keep a working tunnel alive. For a new hostname:

1. Copy the new `trycloudflare.com` origin.
2. Update `RECALLFABRIC_MCP_PUBLIC_URL` and `RECALLFABRIC_OAUTH_AUTHORIZATION_SERVER` (origin only).
3. Restart only RecallFabric; leave the new tunnel running.
4. Update/recreate the ChatGPT MCP connection as required by its UI.
5. Remove/re-add the Claude custom connector with the new URL.
6. Reauthorize both against the **same RecallFabric account**.

Neon data does not change. Old resource-bound OAuth tokens cannot be repurposed for the new hostname. See [restart behavior](#restart-behavior) below.

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

## Full fresh-device installation

The Quick Start above assumes setup is complete. On a new Windows device, follow this section, create the [environment configuration](#configuration) before database/model checks, then return to the Quick Start. Ollama installation is optional and documented later.

### Fresh Windows device prerequisites

Use Windows 10 22H2 or newer, PowerShell, Git, uv, and **Python 3.12** (the CI/Docker version; package requirement >=3.12). Allow disk/RAM for dependencies and FastEmbed. Optional local Ollama models need additional disk/RAM; a GPU is optional.

You need a Neon database supporting `vector`, its credentials, a ChatGPT account/workspace permitted to create custom read/write MCP connections, and a Claude account permitted to add a custom connector. No local PostgreSQL or Docker is needed for this Neon setup.

Install Git and uv if absent, then reopen PowerShell for PATH changes:

```powershell
winget install --id Git.Git --exact
winget install --id astral-sh.uv --exact
git --version
uv --version
```

See [uv installation](https://docs.astral.sh/uv/getting-started/installation/) for alternatives. Cloudflared installation follows below; Ollama is optional for local-LLM workflows. Do not install replacements or start another tunnel on the working demo laptop.

### Clone the working branch

Choose another empty parent if this clone location exists:

```powershell
New-Item -ItemType Directory -Force C:\Projects\New-Recall-Fabric | Out-Null
Set-Location C:\Projects\New-Recall-Fabric
git clone --branch ready-for-mcp https://github.com/tusharsanka4/Capstone-RecallFabric.git Capstone-RecallFabric-Complete
Set-Location Capstone-RecallFabric-Complete
git branch --show-current
```

Run backend commands from `C:\Projects\New-Recall-Fabric\Capstone-RecallFabric-Complete`, including in each new terminal. A clone contains neither credentials nor the protected account file.

### Python environment

```powershell
uv python install 3.12
uv sync --locked --python 3.12
.venv\Scripts\python.exe --version
```

Use the explicit virtual-environment executable; activation and execution-policy changes are unnecessary. `uv.lock` pins dependencies. Do not copy `.venv` between devices.

### Neon, TLS, pgvector, and migrations

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

### FastEmbed and local startup

Download/verify the configured model once; first use needs internet:

```powershell
.venv\Scripts\python.exe -m recallfabric.embeddings --download
```

Keep the backend running in a dedicated terminal:

```powershell
Set-Location C:\Projects\New-Recall-Fabric\Capstone-RecallFabric-Complete
.venv\Scripts\python.exe -m uvicorn recallfabric.main:create_app --factory --host 127.0.0.1 --port 8000 --workers 1 --proxy-headers --forwarded-allow-ips 127.0.0.1
```

Use one worker; do not start a second backend on port 8000. Startup does not migrate the database. In another terminal:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
Invoke-RestMethod http://127.0.0.1:8000/ready
```

`/health`: 200, `status: ok`. `/ready`: 200 with database/vector/revision checks true and `ssl_in_use: true`; fix a 503 before connecting clients. Unauthenticated `/mcp/` returns **401**, as expected. FastAPI's `create_app` supplies authentication; do not expose a separate unauthenticated MCP runner.

### Provision the shared account and protect its key

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

### Install cloudflared and start one Quick Tunnel

Use [official Cloudflare Windows downloads](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/downloads/) (64-bit MSI/executable), or the Windows package:

```powershell
winget install --id Cloudflare.cloudflared --exact
```

Reopen PowerShell and verify:

```powershell
cloudflared --version
```

If PATH has not updated, reopen the terminal. The demo's installed executable is `C:\Program Files (x86)\cloudflared\cloudflared.exe`; invoke a quoted path with PowerShell's `&` operator.

**New device only:** leave this running in its own terminal. Do not replace the working demo tunnel:

```powershell
cloudflared tunnel --protocol http2 --url http://127.0.0.1:8000 --no-autoupdate
```

This is the working port/protocol combination; HTTP/2 avoids reliance on QUIC connectivity. Quick Tunnel needs no Cloudflare account or domain. Do not add an interactive email/Access gate in front of MCP clients. See [Quick Tunnel instructions and limits](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/).

## Configuration

Create `.env` only on the new device. This refuses to overwrite it. Replace admin/database placeholders in a trusted local editor **before starting**. Never paste credentials into chat or commit them.

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
RECALLFABRIC_CHAT_PROVIDER=ollama
RECALLFABRIC_EXTRACTION_PROVIDER=ollama
RECALLFABRIC_ALLOW_LOCAL_OLLAMA=true
RECALLFABRIC_LLM_BASE_URL=http://127.0.0.1:11434/v1
RECALLFABRIC_CHAT_MODEL=qwen2.5:3b-instruct
RECALLFABRIC_EXTRACTION_MODEL=qwen2.5:3b-instruct
RECALLFABRIC_EMBEDDING_PROVIDER=fastembed
RECALLFABRIC_EMBEDDING_MODEL=BAAI/bge-small-en-v1.5
RECALLFABRIC_MCP_JSON_RESPONSE=true
RECALLFABRIC_MCP_STATELESS_HTTP=true
'@ | Set-Content -LiteralPath .env -Encoding ascii
```

Use a password manager for the admin secret, or capture a generated value without printing it:

```powershell
$adminToken = & .venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(48))"
Set-Clipboard -Value $adminToken
# Paste into RECALLFABRIC_ADMIN_TOKEN in the local .env editor; save.
Set-Clipboard -Value ''
```

The placeholder HTTPS origins serve initial local setup only. Replace **both** with the actual tunnel origin in [Quick Start step 3](#step-3--configure-the-public-mcpoauth-origin) before authorizing clients. They contain **origin only**, without `/mcp`, another path, or a trailing slash. The client MCP URL separately ends `/mcp/`.

| Variables | Purpose / requirement for this setup |
|---|---|
| `RECALLFABRIC_ENVIRONMENT`, `RECALLFABRIC_AUTH_ENABLED` | Production, authenticated. Production refuses disabled auth. |
| `RECALLFABRIC_ALLOW_PUBLIC_SIGNUP` | Keep false; administrator provisioning. |
| `RECALLFABRIC_ADMIN_TOKEN` | Required production admin secret, not the user's account key. |
| `RECALLFABRIC_DATABASE_URL` | Required Neon URL; overrides individual DB fields. URL-encode password characters as necessary. |
| `RECALLFABRIC_DB_SSLMODE` | Require TLS, also retaining `sslmode=require` in the URL. |
| `RECALLFABRIC_RUN_MIGRATIONS` | Optional, default false. Controls Docker entrypoint migrations, not Uvicorn startup. Keep false. |
| `RECALLFABRIC_WORKERS` | Optional, default 1. Also pass `--workers 1` to Uvicorn. |
| `RECALLFABRIC_MCP_PUBLIC_URL`, `RECALLFABRIC_OAUTH_AUTHORIZATION_SERVER` | Actual external HTTPS origins for discovery, issuer, and authorization URLs. |
| `RECALLFABRIC_OAUTH_SCOPES` | Optional, default `memory:read memory:write`; retain both for the demo. |
| `RECALLFABRIC_LLM_PROVIDER` | Set `ollama` for the no-hosted-LLM-key path. |
| `RECALLFABRIC_CHAT_PROVIDER`, `RECALLFABRIC_EXTRACTION_PROVIDER` | Optional overrides; explicitly set `ollama` to avoid accidental hosted-provider selection. |
| `RECALLFABRIC_ALLOW_LOCAL_OLLAMA`, `RECALLFABRIC_LLM_BASE_URL` | Accept local-provider configuration in production and use a loopback address; this does not start or require the Ollama service for ordinary MCP tools. Never tunnel Ollama. |
| `RECALLFABRIC_CHAT_MODEL`, `RECALLFABRIC_EXTRACTION_MODEL` | Explicit working model `qwen2.5:3b-instruct`. |
| `RECALLFABRIC_EMBEDDING_PROVIDER`, `RECALLFABRIC_EMBEDDING_MODEL` | FastEmbed, `BAAI/bge-small-en-v1.5`, 384 dimensions; match existing stored vectors. |
| `RECALLFABRIC_MCP_JSON_RESPONSE`, `RECALLFABRIC_MCP_STATELESS_HTTP` | Both true for Quick Tunnel. Authentication stays enabled. |

`.env` loads from the working directory; `.env.local` is not automatically loaded. Process environment overrides `.env`. The broad [.env.example](.env.example) is a settings reference, not this production recipe. If using it as a base, clear its default `RECALLFABRIC_DB_PASSWORD` for a Neon URL; production rejects the local default password. No OpenAI/Anthropic/Gemini key is needed here. Leave relevance/entity settings unchanged.

The Ollama provider/model entries select a valid optional backend provider; they do not start Ollama or route ChatGPT/Claude reasoning through it. The production validator requires the explicit local opt-in when that provider is selected, even if no local-LLM request is made. A running provider is needed only for the server-side LLM paths described below; hosted providers remain supported alternatives.

## Ollama and local extraction

### Ollama is optional for MCP usage

```text
ChatGPT or Claude -> their own LLM -> RecallFabric MCP tools -> FastEmbed -> Neon + pgvector
```

A running Ollama server is not required for normal `remember` (`extract=false`), `recall`, `list_memories`, `update_memory`, `forget`, or cross-client MCP continuity. ChatGPT and Claude perform their own reasoning and select tools. FastEmbed remains required for semantic embeddings/retrieval unless another embedding provider is explicitly configured; existing stored vectors must remain compatible.

Ollama support remains available for local RecallFabric `/chat`, extraction workflows, development/testing, and standalone operation where the MCP host is not supplying the reasoning. The current optional local model is `qwen2.5:3b-instruct`.

**Existing implementation boundary:** `remember(extract=true)` invokes the configured extraction LLM. Ordinary `remember` may also invoke that provider to classify an ambiguous conflict with an existing memory; provider failure skips that conflict check rather than preventing storage. It may add latency and does not guarantee automatic supersession. For reliable changed-state updates without a backend LLM, the client should recall the current record and call `update_memory` with its ID and `expected_version`. These paths are documented as implemented; no production behavior is changed here.

### Optional local Ollama installation and startup

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

The working model is [`qwen2.5:3b-instruct`](https://ollama.com/library/qwen2.5:3b-instruct). Ollama handles extraction, conflict decisions, and optional backend chat. **FastEmbed remains the embedding provider**; do not switch embeddings to Ollama. Local-production Ollama requires the explicit loopback opt-in below.

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

Commands and paths were checked against the repository, PowerShell syntax, environment validation, and official client documentation. This documentation-only update does not start/restart services, create a tunnel, modify origins, run migrations, or claim a new live client connection. Earlier public verification is historical evidence, not a promise that a temporary hostname remains available. Follow the Quick Start to verify your own installation.
