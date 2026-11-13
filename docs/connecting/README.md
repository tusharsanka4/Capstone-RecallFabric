# Connecting to RecallFabric via MCP

RecallFabric ships as a Model Context Protocol (MCP) server supporting:
1. **Streamable HTTP Transport (`/mcp`)**: Connect Claude Desktop, Cursor, Windsurf, VS Code, and custom agent frameworks over the internet using standard HTTP POST requests with Server-Sent Events (SSE) streaming.
2. **Local Stdio Transport**: Run directly inside local agent environments via `python -m recallfabric.mcp_server`.

---

## Remote Connection Configurations

### 1. Claude Desktop

Claude Desktop connects to remote MCP servers using the `mcp-remote` bridge connector.

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

### Known Limitation: OAuth 2.1
The official MCP ecosystem currently relies primarily on Bearer API keys and HTTP headers for remote authentication. While OAuth 2.1 authorization-code flow is drafted in MCP specifications, client implementations (such as Claude Desktop and IDE connectors) do not yet offer standardized browser-based authorization flows. As a result, RecallFabric uses Bearer API keys for production remote deployment, and lists OAuth 2.1 authorization code grant as a planned future enhancement when client support stabilizes.

---

## Available MCP Tools, Resources & Prompts

### Tools

| Tool | Signature | When LLM Calls It |
|---|---|---|
| `remember` | `(content: str, type="fact", importance=0.5, extract=False)` | Call when the user states a durable fact, preference, profile attribute, constraint, or goal. Set `extract=true` to parse multiple facts from conversation turns. |
| `recall` | `(query: str, limit=5, type=None)` | Call at the start of a conversation and before answering questions about the user to inject relevant context. |
| `forget` | `(memory_id=None, query=None, confirm=False)` | Call when the user asks to remove or forget information. Supports direct deletion or semantic search with confirmation. |
| `list_memories` | `(type=None, status="active", limit=50)` | Call when reviewing user memory inventory or filtering by category. |
| `update_memory` | `(id: str, content=None, type=None, importance=None)` | Call when the user updates or refines an existing memory. |
| `get_memory_history` | `(id: str)` | Call when inspecting provenance and audit history of a memory. |
| `get_profile` | `(limit=20)` | Call at session start to obtain a structured summary of active memories grouped by category. |

### Resources

- `memory://profile`: Returns the active user profile summary and top active memories grouped by category.

### Prompts

- `use_memory`: Model guidance and system instructions explaining best practices for using RecallFabric memory tools.

---

## Step-by-Step cURL Handshake Test

You can verify your remote RecallFabric MCP server from the command line using standard `curl` commands:

### Step 1: Initialize MCP Session
```bash
curl -i -X POST https://<your-host>/mcp \
  -H "Authorization: Bearer <your-api-key>" \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
      "protocolVersion": "2024-11-05",
      "capabilities": {},
      "clientInfo": {"name": "curl-test", "version": "1.0"}
    }
  }'
```
*Take note of the `mcp-session-id` header in the HTTP response.*

### Step 2: Acknowledge Initialization
```bash
curl -i -X POST https://<your-host>/mcp \
  -H "Authorization: Bearer <your-api-key>" \
  -H "mcp-session-id: <session-id-from-step-1>" \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "method": "notifications/initialized",
    "params": {}
  }'
```

### Step 3: List Tools
```bash
curl -i -X POST https://<your-host>/mcp \
  -H "Authorization: Bearer <your-api-key>" \
  -H "mcp-session-id: <session-id-from-step-1>" \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 2,
    "method": "tools/list",
    "params": {}
  }'
```

### Step 4: Call `remember` Tool
```bash
curl -i -X POST https://<your-host>/mcp \
  -H "Authorization: Bearer <your-api-key>" \
  -H "mcp-session-id: <session-id-from-step-1>" \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 3,
    "method": "tools/call",
    "params": {
      "name": "remember",
      "arguments": {
        "content": "User prefers concise Python 3.12 code using type hints",
        "type": "preference",
        "importance": 0.9
      }
    }
  }'
```

### Step 5: Call `recall` Tool
```bash
curl -i -X POST https://<your-host>/mcp \
  -H "Authorization: Bearer <your-api-key>" \
  -H "mcp-session-id: <session-id-from-step-1>" \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 4,
    "method": "tools/call",
    "params": {
      "name": "recall",
      "arguments": {
        "query": "coding preferences",
        "limit": 3
      }
    }
  }'
```

### Step 6: Read `memory_profile` Resource
```bash
curl -i -X POST https://<your-host>/mcp \
  -H "Authorization: Bearer <your-api-key>" \
  -H "mcp-session-id: <session-id-from-step-1>" \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 5,
    "method": "resources/read",
    "params": {
      "uri": "memory://profile"
    }
  }'
```

---

## Non-MCP Clients (Custom GPTs, Gemini Gems, & OpenAI-Compatible Proxy)

For AI applications, models, or platforms that do not speak MCP:

- **Custom GPTs & Gemini Gems**: See [Custom GPT & Gemini Gem Integration Kit](custom-gpt.md) for exact OpenAPI 3.1 action schemas and system instructions to paste.
- **OpenAI-Compatible Memory Proxy**: Point any OpenAI SDK app's `base_url` directly at `https://<your-host>/v1/proxy/` (or `/proxy/`) to automatically inject recalled memories and persist new facts without altering application code.
- **Webhook Ingestion**: Post conversation transcripts to `POST /v1/ingest` for asynchronous background fact extraction.
- **Browser Extension**: Load `extensions/browser/` (Manifest V3) to inject memory recall directly into the ChatGPT, Claude, and Gemini web interfaces.

