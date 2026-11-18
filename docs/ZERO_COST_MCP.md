# Zero-hosting-cost MCP demonstration

Verified 2026-11-19. No paid hosting, purchases, commits, or pushes.

## Current running endpoint

https://aids-authentic-trail-webshots.trycloudflare.com/mcp/

Backend: 127.0.0.1:8000, production, authentication enabled, signup disabled,
one worker. Neon TLS and pgvector 0.8.7 verified. Additive migration e1a2b3c4d501
applied transactionally; the prior 8 memory revisions were preserved. One new synthetic
memory was added under a new isolated demo tenant; no existing tenant memories were edited.

Ollama: loopback 127.0.0.1:11434, qwen2.5:3b-instruct. Local generation returned 200.
FastEmbed: BAAI/bge-small-en-v1.5, 384 dimensions. No hosted LLM API calls were made.
The new ALLOW_LOCAL_OLLAMA opt-in permits loopback Ollama in production while retaining
all production auth checks. It does not enable external Ollama hosts.

Quick Tunnels do not support SSE. The backend uses opt-in MCP_JSON_RESPONSE and
MCP_STATELESS_HTTP settings. Defaults remain unchanged for other deployments. Cloudflare
QUIC was blocked by the network, so this running tunnel uses HTTP/2 to Cloudflare.
Application HTTPS and OAuth remain enabled.

## Actual public tests

- /health and /ready: HTTP 200.
- Both OAuth metadata endpoints: HTTP 200, actual external origin advertised.
- Unauthenticated /mcp/: HTTP 401.
- Two independent DCR + authorization-code + PKCE S256 grants approved against one demo
  account key; both used the advertised resource/audience.
- First grant called remember; second grant called recall and received the synthetic memory.
- Direct Neon query verified the synthetic account, memory ID and content.
- Official MCP SDK over public HTTPS initialized protocol 2025-11-25, discovered 11 tools,
  and retrieved the persisted memory through list_memories in a new session.
- Memory ID: a2d8db6f-6304-499b-aa86-12e651467f73 (synthetic demo tenant only).
- ChatGPT and Claude: not tested, not claimed connected.

Detailed test evidence is in the access-restricted directory
C:/Projects/New-Recall-Fabric/.recallfabric-demo/public-result.json.
The account key for authorizing BOTH real clients is in account.json in that same directory.
That directory grants access only to the current Windows user. Do not paste the key into
chat, source code or the MCP URL; enter it only into RecallFabric's OAuth consent form.

## Keep running / restart

Keep the laptop awake, network connected, and all three processes running. Current process
sessions were started by the agent; no Windows startup service was installed.

From the repository directory, run these in separate terminals when a restart is needed:

```powershell
ollama serve
& 'C:/Program Files (x86)/cloudflared/cloudflared.exe' tunnel --protocol http2 --url http://127.0.0.1:8000 --no-autoupdate
```

The second command prints a NEW origin. Before starting the backend, replace BOTH origin
values in C:/Projects/New-Recall-Fabric/.recallfabric-demo/run_local.py with that new origin:

```powershell
.venv/Scripts/python.exe C:/Projects/New-Recall-Fabric/.recallfabric-demo/run_local.py
```

Do not start a second copy while the current process is running. Existing .env/.env.local
were not edited. The launch script generates its admin secret in memory on each start.
An existing demo API key survives restart because it is persisted in Neon.

Changing the Quick Tunnel origin changes the OAuth issuer and resource audience. Recreate
or update the ChatGPT/Claude connector URL, refresh discovery, and complete OAuth again.
Old access/refresh grants bound to the former resource must not be reused. Never change
stored token audiences to bypass the check. No stable domain is required for this temporary
demo; a stable setup needs a named tunnel and a domain you already control. None was purchased.

## ChatGPT

Current official instructions:
https://help.openai.com/en/articles/12584461-connecting-custom-mcp-servers-in-chatgpt

Full custom MCP read/write availability is documented for Business and Enterprise/Edu on
ChatGPT web, subject to workspace policies. Business requires admin/owner; Enterprise/Edu
can grant selected developers access through RBAC. This user's plan/role was not verified;
browser access was unavailable. Do not infer eligibility from a successful protocol probe.

1. Open Plugins on ChatGPT web. Select +, then Add custom MCP server.
2. Name it RecallFabric and enter the full current /mcp/ HTTPS URL.
3. Choose OAuth / automatic client registration when offered. Review the risk warning.
4. Create as a plugin; approve the RecallFabric consent page with the demo account key.
5. Confirm remember, recall, list_memories and update_memory appear and are enabled.
6. Install/select the plugin in a new chat. Explicitly request storing a unique synthetic fact;
   approve the write and check the tool invocation/result.
7. In another chat select the plugin and request recall of that fact. Check the actual tool
   invocation. Then verify the new row in Neon. Neither real-client step has been performed.

If using the legacy interface: Settings or Workspace settings -> Apps -> Create, provide
OAuth and endpoint, Scan Tools, authorize, then Create. If the current custom MCP option or
write permission is absent, a workspace admin must grant it; do not disable server auth.

## Claude

Current official instructions:
https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp

1. Customize -> Connectors -> + Add -> Add custom connector (organization owners may need
   to add it in organization settings first).
2. Enter RecallFabric and the same current /mcp/ URL.
3. Choose Sign in now and Register automatically; the server implements DCR, not CIMD.
4. Authorize with the SAME demo account key, obtaining an independent OAuth grant.
5. Enable the connector in a new chat and ask to list/recall the stored synthetic memory.
6. Request an update using its current expected_version, then retrieve it through the other
   client. Do not claim connection until Claude actually invokes the tool.

No client subscription or domain was purchased. Existing Neon usage remains subject to
its current account allowance; hosting runs locally with a free temporary tunnel and a local LLM.
