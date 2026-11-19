# RecallFabric

RecallFabric is a shared persistent memory layer for AI assistants using MCP. ChatGPT and Claude retain their own native memories; RecallFabric provides shared, account-scoped memories across clients. It does not automatically copy entire conversations.

This is the canonical setup guide for the working **Windows backend + Cloudflare Quick Tunnel + Neon** demonstration. Follow fresh-device steps only on a new installation. Do not overwrite configuration or reprovision an already connected account.

## 1. Current capabilities

- MCP Streamable HTTP, ChatGPT custom MCP support, and Claude custom connectors.
- Shared account-scoped memory, tenant isolation, FastEmbed, and pgvector.
- Semantic recall, relevance filtering, entity/project-aware recall, and memory supersession.
- Assistant-recommendation acceptance, automatic recall guidance, and conservative durable-memory guidance.
- OAuth authorization-code flow with PKCE S256, resource/audience binding, scopes, and independent client grants.
- Memory history and provenance.

Core tools: `recall`, `remember`, `update_memory`, `forget`, `list_memories`, `get_profile`, `get_memory_history`, `get_provenance`. Legacy aliases remain available. The client model controls invocation; automatic recall/write is not guaranteed.

## 2. Architecture

```mermaid
flowchart TD
    A[ChatGPT] --> T[Cloudflare Tunnel / HTTPS]
    B[Claude] --> T
    C[Other MCP client] --> T
    T --> R[RecallFabric FastAPI + MCP]
    R --> E[FastEmbed: local embeddings]
    E --> N[(Neon PostgreSQL + pgvector)]
    R --> N
    R --> O[Local Ollama: extraction / conflicts / chat]
```

Cloudflare only exposes the locally running backend publicly. Python, FastEmbed, and Ollama run on the laptop; Neon holds durable data. Quick Tunnel uses stateless MCP HTTP with JSON responses because it does not support SSE. This is a demo/development setup without an uptime guarantee.

## 3. Fresh Windows device prerequisites

Use Windows 10 22H2 or newer, PowerShell, Git, uv, and **Python 3.12** (the CI/Docker version; package requirement >=3.12). Allow disk/RAM for dependencies, FastEmbed, and a local 3B Ollama model. A GPU is optional. A laptop running Ollama needs more memory than a backend-only container.

You need a Neon database supporting `vector`, its credentials, a ChatGPT account/workspace permitted to create custom read/write MCP connections, and a Claude account permitted to add a custom connector. No local PostgreSQL or Docker is needed for this Neon setup.

Install Git and uv if absent, then reopen PowerShell for PATH changes:

```powershell
winget install --id Git.Git --exact
winget install --id astral-sh.uv --exact
git --version
uv --version
```

See [uv installation](https://docs.astral.sh/uv/getting-started/installation/) for alternatives. Ollama and cloudflared installation follow below. Do not install replacements or start another tunnel on the working demo laptop.

## 4. Clone the working branch

Choose another empty parent if this clone location exists:

```powershell
New-Item -ItemType Directory -Force C:\Projects\New-Recall-Fabric | Out-Null
Set-Location C:\Projects\New-Recall-Fabric
git clone --branch ready-for-mcp https://github.com/tusharsanka4/Capstone-RecallFabric.git Capstone-RecallFabric-Complete
Set-Location Capstone-RecallFabric-Complete
git branch --show-current
```

Run backend commands from `C:\Projects\New-Recall-Fabric\Capstone-RecallFabric-Complete`, including in each new terminal. A clone contains neither credentials nor the protected account file.

## 5. Python environment

```powershell
uv python install 3.12
uv sync --locked --python 3.12
.venv\Scripts\python.exe --version
```

Use the explicit virtual-environment executable; activation and execution-policy changes are unnecessary. `uv.lock` pins dependencies. Do not copy `.venv` between devices.

## 6. Ollama setup

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

## 7. Environment configuration

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

The placeholder HTTPS origins serve initial local setup only. Replace **both** with the actual tunnel origin in section 12 before authorizing clients. They contain **origin only**, without `/mcp`, another path, or a trailing slash. The client MCP URL separately ends `/mcp/`.

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
| `RECALLFABRIC_ALLOW_LOCAL_OLLAMA`, `RECALLFABRIC_LLM_BASE_URL` | Local-production opt-in and loopback API address. Never tunnel Ollama itself. |
| `RECALLFABRIC_CHAT_MODEL`, `RECALLFABRIC_EXTRACTION_MODEL` | Explicit working model `qwen2.5:3b-instruct`. |
| `RECALLFABRIC_EMBEDDING_PROVIDER`, `RECALLFABRIC_EMBEDDING_MODEL` | FastEmbed, `BAAI/bge-small-en-v1.5`, 384 dimensions; match existing stored vectors. |
| `RECALLFABRIC_MCP_JSON_RESPONSE`, `RECALLFABRIC_MCP_STATELESS_HTTP` | Both true for Quick Tunnel. Authentication stays enabled. |

`.env` loads from the working directory; `.env.local` is not automatically loaded. Process environment overrides `.env`. The broad [.env.example](.env.example) is a settings reference, not this production recipe. If using it as a base, clear its default `RECALLFABRIC_DB_PASSWORD` for a Neon URL; production rejects the local default password. No OpenAI/Anthropic/Gemini key is needed here. Leave relevance/entity settings unchanged.

## 8. Neon, TLS, pgvector, and migrations

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

## 9. FastEmbed and local startup

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

## 10. Provision the shared account and protect its key

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

## 11. Install cloudflared and start one Quick Tunnel

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

## 12. Capture the URL and configure OAuth

Cloudflared prints an origin such as `https://random-name.trycloudflare.com`. In the administrative terminal:

```powershell
$publicOrigin = 'https://YOUR-ACTUAL-NAME.trycloudflare.com'
```

Edit these entries in the new device's ignored `.env`:

```dotenv
RECALLFABRIC_MCP_PUBLIC_URL=https://YOUR-ACTUAL-NAME.trycloudflare.com
RECALLFABRIC_OAUTH_AUTHORIZATION_SERVER=https://YOUR-ACTUAL-NAME.trycloudflare.com
```

Both are **origin only**. Client MCP URL: **`https://YOUR-ACTUAL-NAME.trycloudflare.com/mcp/`**. Metadata identifies the canonical protected resource ending `/mcp`; token audiences bind to that resource. Do not append `/mcp` to either origin setting.

Stop **only the backend** with Ctrl+C, then repeat section 9's Uvicorn command. **Leave cloudflared running.** Reloading Python picks up origins; restarting the tunnel produces another hostname. Authorize clients only after discovery advertises the actual URL.

## 13. Verify public HTTPS and MCP

```powershell
Invoke-RestMethod "$publicOrigin/health"
Invoke-RestMethod "$publicOrigin/ready"
Invoke-RestMethod "$publicOrigin/.well-known/oauth-protected-resource/mcp"
Invoke-RestMethod "$publicOrigin/.well-known/oauth-authorization-server"
curl.exe -sS -o NUL -w '%{http_code}' "$publicOrigin/mcp/"
```

Health/readiness/discovery should return 200. Resource metadata must identify `$publicOrigin/mcp`; authorization metadata advertises the actual HTTPS issuer, PKCE S256, and authorization/token/registration endpoints. The last command should print **401** without a token, not an HTML gate.

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

## 14. Connect ChatGPT

[Current official instructions](https://help.openai.com/en/articles/12584461-connecting-custom-mcp-servers-in-chatgpt) describe full custom MCP support on Business and Enterprise/Edu web workspaces, subject to administrator permissions. Check **Create plugins with MCPs** access; a fresh account is not automatically eligible for read/write. Keep the already connected demo account intact.

1. ChatGPT web: **Plugins > + > Add custom MCP server** (permission required).
2. Name **RecallFabric**; remote URL `https://<your-tunnel>/mcp/`. Use OAuth/automatic registration, never an unauthenticated configuration.
3. Continue creation, review permissions, and paste the protected file's **`api_key`** into RecallFabric consent. Approve.
4. Allow the continuation page to return to ChatGPT or use its link; finish the dialog.
5. Confirm `remember`, `recall`, `list_memories`, `update_memory` are discovered. Enable RecallFabric in the conversation.

Older interfaces may use Settings > Apps or a custom/developer-app area; follow the equivalent supported screen. Read-only search does not prove write eligibility. After description changes, use **Refresh** where available and a fresh chat rather than deleting a working connection. Writes may require client confirmation.

Test: **“Remember that Project Orion uses Spring Boot, React and PostgreSQL.”** Verify actual `remember` invocation. In a fresh enabled chat: **“Let's continue Project Orion.”** Check `recall` activity and context. Guidance encourages automatic use but cannot guarantee it; an answer alone is not proof.

## 15. Connect Claude to the same account

[Current Claude instructions](https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp) support custom connectors on Free and paid plans; **Free permits one custom connector at a time**. Workspace restrictions may apply.

1. **Customize > Connectors > Add custom connector**; select **Web** if asked.
2. Name **RecallFabric**, same `https://<your-tunnel>/mcp/` URL.
3. **Sign in now > Register automatically** when offered. RecallFabric supports dynamic registration; no invented client secret is needed.
4. At RecallFabric consent, use the **same account `api_key` as ChatGPT**. Approve and return.
5. Fresh enabled chat: **“What do you know about Project Orion?”** Verify a real call retrieves the memory written through ChatGPT.

If the tunnel URL changes, remove/recreate the old connector as its UI requires and reauthorize. Backend-only restart at the same origin does not require this.

## 16. Cross-client demo and conservative writes

Use isolated synthetic project data:

1. ChatGPT: **“Remember that Project Helios uses Spring Boot and PostgreSQL.”** Verify successful `remember`.
2. Fresh Claude chat: **“What do you know about Project Helios?”** Verify `recall`.
3. Claude: **“Project Helios now uses Django instead of Spring Boot; PostgreSQL is unchanged.”** Verify it recalls the current record and calls `update_memory` with ID/expected version. If not automatic, explicitly request the update for the demo.
4. Fresh ChatGPT chat: **“What backend and database does Project Helios use now?”** Verify Django/PostgreSQL. Spring Boot should be superseded, not current; history can still expose it.

This proves persistent account sharing through independent OAuth grants, not native history synchronization. Natural durable statements such as “My secondary monitor is vertical for coding” or “Nova now uses Django” qualify without “remember this.” Temporary feelings, tentative plans, hypotheticals, quotations, general knowledge, and unaccepted assistant recommendations do not. Routine save narration is discouraged.

MCP receives tool calls, not ordinary client messages. Existing opt-in extraction retains its filters/acceptance gate; explicit `remember` is a write tool, not a second message classifier. Clarify ambiguous updates. Memory is context, not unquestionable truth; current user corrections take precedence.

## 17. Restart behavior

**Backend restart:** stop/restart only Uvicorn. Keeping cloudflared alive preserves the URL and existing grants. Check readiness/discovery afterward. Metadata refresh may be needed; reconnection/reauthorization is not normally necessary at the same origin.

**Cloudflared restart:** Quick Tunnel hostnames change. Then:

1. Capture the new HTTPS origin.
2. Update both public-origin settings.
3. Restart only the backend and verify readiness/discovery.
4. Update/recreate ChatGPT's connection and Claude's connector as required.
5. Start fresh OAuth flows for both, using the same account key.

Old resource-bound tokens are not valid for the new hostname. Never rewrite audiences or weaken validation.

**Laptop shutdown:** service becomes unavailable; Neon memories remain stored. Start Ollama/backend and a new tunnel after boot, then follow the hostname-change procedure. Prevent sleep during the demo. Stable hostnames require a separately configured named tunnel/domain; this guide purchases nothing.

## 18. Troubleshooting

### CSP OAuth continuation issue

Consent posts to relative same-origin `/auth/oauth/authorize/approve`, preserving `Content-Security-Policy: form-action 'self'`. Approval returns a same-origin **200 continuation page** with navigation/link to the registered callback, avoiding a cross-origin form-POST redirect chain. Let it continue or click its link. Check public-origin/proxy HTTPS metadata; never relax CSP with wildcards.

### 400 `access_denied` after failed authorization

Transactions are one-use and expire. Consumed/expired requests cannot be reused from an old consent tab. Start a **fresh authorization from the client**. If it persists, check key validity/required fields; never bypass CSRF or reuse a code.

### Irrelevant or missing memories

`limit` is a maximum, not a required count. Relevance filtering may return zero. Entity-aware recall separates named projects and permits comparisons. See [relevance semantics](docs/RECALL_RELEVANCE.md) and [entity matching](docs/ENTITY_MEMORY.md). Do not lower the working threshold or change embeddings as an initial fix.

### Clients do not automatically recall/write

Enable RecallFabric, refresh metadata where supported, and start a fresh chat. Inspect actual tool activity. Client models decide invocation; not all clients automatically load `use_memory`. General knowledge, temporary, and speculative statements should not trigger writes. See [guidance](docs/MCP_TOOL_GUIDANCE.md).

### Backend works locally but not publicly / tunnel changed

Check the existing cloudflared process, printed URL, local port 8000, public `/ready`, and both discovery paths. Keep the original tunnel alive. Check outbound access and avoid interactive Cloudflare gates. A 401 on unauthenticated MCP is correct; 503 readiness requires DB/vector/revision/TLS investigation. Process environment overrides `.env`. For a changed hostname, follow section 17, not just a client URL edit.

### Blank provider/model/database errors

Use explicit provider/model values above. Verify Ollama lists `qwen2.5:3b-instruct`, FastEmbed's cache is accessible, Neon points to the intended branch, and migrations match head. Never print connection strings. Do not carry default local database passwords into production.

## 19. Security notes

- Never commit `.env`, `.env.local`, account/session files, API keys, OAuth tokens, Neon credentials, or Cloudflare credentials. Review staged changes even with `.gitignore` protection.
- Keep `account.json` outside Git with restrictive permissions; copy keys only into the correct HTTPS consent page and clear the clipboard.
- Signup stays disabled, auth enabled, and scopes intact. The admin token is not a client account key.
- Same account for continuity, independent client OAuth grants. Never share access/refresh tokens between clients.
- Tunnel only the backend, never PostgreSQL/Ollama ports. Use synthetic data; do not reset databases or overwrite real memories to repair setup.

## 20. Developer checks and specialist references

Focused checks, without benchmarks or hosted migrations:

```powershell
.venv\Scripts\python.exe -m pytest tests/test_auto_write_guidance.py tests/test_mcp_guidance.py tests/test_conversation_decisions.py tests/test_mcp_contracts.py tests/test_recall_relevance.py tests/test_entity_memory.py tests/test_oauth_consent_proxy.py tests/test_public_mcp_security.py -q -p no:cacheprovider
.venv\Scripts\ruff.exe check .
.venv\Scripts\python.exe scripts/generate_tool_schemas.py --check
git diff --check
```

- [MCP contract, stdio, and lifecycle checks](docs/MCP_SERVER_SETUP.md)
- [OAuth architecture](docs/UNIVERSAL_AI_MEMORY_CONNECTOR.md)
- [IDE and legacy bridge configurations](docs/connecting/README.md)
- [Cloud alternatives](docs/deployment.md) and [Render environment reference](deploy.render.env.example)
- [Zero-cost verification record](docs/ZERO_COST_MCP.md)
- [Python SDK](sdk/python/README.md) and [JavaScript SDK](sdk/js/README.md)
- [Security reference](docs/security.md)

Historical capstone reports/evaluation artifacts are retained as snapshots, not instructions to replace a working deployment.

## 21. Verification scope

This guide uses the repository's actual entrypoint, settings, admin API, revision, model, and MCP probe. The current installation passed public readiness/TLS/vector checks, initialization, discovery, and authenticated recall after backend-only reload. Its URL and OAuth metadata stayed unchanged.

After an interruption later in this work session, neither backend nor tunnel process was present and the former Quick Tunnel hostname no longer resolved. The successful public checks above precede that loss. The backend was restored and local authenticated discovery/recall passed with unchanged contracts and OAuth metadata. No replacement tunnel was created and no OAuth origin was changed; the old hostname is not a claim of current availability. Ollama also became unavailable; starting it was blocked by automatic approval review, so local extraction/generation still needs a manual Ollama start. Recovering public service may require the hostname-change procedure in section 17.

Dependency resolution was checked without replacing the running environment. Installation, cloning, first-time downloads, new-account provisioning, and new-database migration are documented procedures, not actions rerun against the live demo. UI steps were checked against official docs; actual ChatGPT/Claude automatic-write behavior still needs the manual tests above. Server checks alone do not prove client behavior.
