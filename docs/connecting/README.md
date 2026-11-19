# Connecting to RecallFabric via MCP

For current ChatGPT/Claude OAuth connections, account provisioning, and Quick Tunnel
setup, use the [canonical README](../../README.md). This reference covers optional
IDE configurations and legacy bridges; these clients may have different UI versions.

RecallFabric ships as a Model Context Protocol (MCP) server supporting:
1. **Streamable HTTP Transport (`/mcp/`)**: Remote HTTP MCP, with JSON responses and stateless mode for Quick Tunnel; SSE is available in other supported deployments.
2. **Local Stdio Transport**: Run directly inside local agent environments via `python -m recallfabric.mcp_server`.

---

## Remote Connection Configurations

### 1. Legacy Claude Desktop bridge (optional)

Current Claude supports direct remote OAuth connectors; follow the main README.
The following legacy `mcp-remote` bridge is an optional alternative for clients using
local `mcpServers` configuration, not a prerequisite for Claude's custom connector.

Edit your Claude Desktop configuration file:
- **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`
- **Linux**: `~/.config/Claude/claude_desktop_config.json`

Add the following to `"mcpServers"`:

```json
{
  "mcpServers": {
    "recallfabric": {
      "command": "npx",
      "args": [
        "-y",
        "mcp-remote",
        "https://<your-host>/mcp",
        "--header",
        "Authorization: Bearer <your-api-key>"
      ]
    }
  }
}
```

### 2. Cursor IDE

In Cursor, open **Settings** > **Features** > **MCP Servers**, or create `.cursor/mcp.json` in your workspace:

```json
{
  "mcpServers": {
    "recallfabric": {
      "url": "https://<your-host>/mcp",
      "headers": {
        "Authorization": "Bearer <your-api-key>"
      }
    }
  }
}
```

### 3. VS Code (Cline / Continue / Roo Code / Copilot)

In your VS Code extension settings or global MCP settings file:

```json
{
  "mcpServers": {
    "recallfabric": {
      "url": "https://<your-host>/mcp",
      "headers": {
        "Authorization": "Bearer <your-api-key>"
      }
    }
  }
}
```

### 4. Windsurf (Codeium)

Edit `~/.codeium/windsurf/mcp_config.json`:

```json
{
  "mcpServers": {
    "recallfabric": {
      "serverUrl": "https://<your-host>/mcp",
      "headers": {
        "Authorization": "Bearer <your-api-key>"
      }
    }
  }
}
```

### 5. Generic MCP Client Configuration

Standard JSON configuration schema compatible with modern MCP tools:

```json
{
  "$schema": "https://modelcontextprotocol.io/schema/mcp-config.json",
  "mcpServers": {
    "recallfabric": {
      "url": "https://<your-host>/mcp",
      "transport": "streamable-http",
      "headers": {
        "Authorization": "Bearer <your-api-key>"
      }
    }
  }
}
```

---

## Authentication & Security

- **Bearer Token Auth**: Every remote HTTP request to `/mcp` must include `Authorization: Bearer <your-api-key>` (or `X-API-Key: <your-api-key>`).
- **User Scoping**: The API key is securely resolved on the server to the authenticated `user_id`. Tool signatures intentionally omit `user_id` so LLMs cannot impersonate other users or tamper with data boundaries.
- **Session Isolation**: MCP session tokens (`mcp-session-id`) are verified per user. A session created by User A cannot be accessed or manipulated by User B.
- **Rate Limiting & Size Limits**: Remote calls to `/mcp` are protected by token-bucket rate limiting (`RECALLFABRIC_RATE_LIMIT_RPS` and `RECALLFABRIC_RATE_LIMIT_BURST`) and request body limits (`RECALLFABRIC_MAX_REQUEST_SIZE_BYTES`).
- **Audit Logging**: All MCP tool executions (`remember`, `recall`, `forget`, etc.) and authentication events are logged to the PostgreSQL audit trail with timestamps and client IP addresses.

### OAuth support
RecallFabric implements browser authorization, PKCE S256, dynamic client registration,
resource/audience binding, scopes, and refresh rotation. ChatGPT and Claude use separate
OAuth grants against the same RecallFabric account. Direct account-key headers remain
supported for SDK probes and compatible IDE clients. Follow the main README for consent.

---

## Available MCP Tools, Resources & Prompts

### Tools

| Tool | Signature | When LLM Calls It |
|---|---|---|
| `remember` | `(content: str, type="fact", importance=0.5, extract=False)` | Call when the user states a durable fact, preference, profile attribute, constraint, or goal. Set `extract=true` to parse multiple facts from conversation turns. |
| `recall` | `(query: str, limit=5, type=None)` | Recall when stored prior context is relevant; skip self-contained general knowledge. |
| `forget` | `(memory_id=None, query=None, confirm=False, expected_version=None)` | Preview first; confirmed deletion requires the current expected version. |
| `list_memories` | `(type=None, status="active", limit=50)` | Call when reviewing user memory inventory or filtering by category. |
| `update_memory` | `(id: str, expected_version: int, content=None, type=None, importance=None)` | Call when the user updates or refines an existing memory. |
| `get_memory_history` | `(id: str)` | Call when inspecting provenance and audit history of a memory. |
| `get_provenance` | `(id: str)` | Inspect owner-scoped source/event records. |
| `get_profile` | `(limit=20)` | Call at session start to obtain a structured summary of active memories grouped by category. |

### Resources

- `memory://profile`: Returns the active user profile summary and top active memories grouped by category.

### Prompts

- `use_memory`: Model guidance and system instructions explaining best practices for using RecallFabric memory tools.

---

## Protocol verification

Use the authenticated official SDK probe in the [main README](../../README.md#13-verify-public-https-and-mcp). It initializes the negotiated protocol and verifies tools, resources, and prompts without writing sample memories. The old manual session/cURL sequence was specific to a stateful transport and is unnecessary for the current stateless Quick Tunnel setup.

## Non-MCP Clients (Custom GPTs, Gemini Gems, & OpenAI-Compatible Proxy)

For AI applications, models, or platforms that do not speak MCP:

- **Custom GPTs & Gemini Gems**: See [Custom GPT & Gemini Gem Integration Kit](custom-gpt.md) for exact OpenAPI 3.1 action schemas and system instructions to paste.
- **OpenAI-Compatible Memory Proxy**: Point any OpenAI SDK app's `base_url` directly at `https://<your-host>/v1/proxy/` (or `/proxy/`) to automatically inject recalled memories and persist new facts without altering application code.
- **Webhook Ingestion**: Post conversation transcripts to `POST /v1/ingest` for asynchronous background fact extraction.
- **Browser Extension**: Load `extensions/browser/` (Manifest V3) to inject memory recall directly into the ChatGPT, Claude, and Gemini web interfaces.

