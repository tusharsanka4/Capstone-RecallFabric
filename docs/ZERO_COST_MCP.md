# Zero-hosting-cost MCP demonstration

Historical verification snapshot from 2026-11-19. For all setup, account provisioning, client connection, and restart instructions, use the [canonical README](../README.md). This record does not assert that the temporary hostname is still running.

## Endpoint at the verification checkpoint

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

## Current operational guidance

Setup and restart procedures have been consolidated into the main README. Preserve an existing tunnel while reloading only the backend. A lost Quick Tunnel cannot be assumed recoverable at the same hostname. Actual ChatGPT/Claude behavior requires real-client tool calls, not just the protocol tests recorded above.
