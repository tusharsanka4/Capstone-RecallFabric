# RecallFabric API Reference

RecallFabric exposes a versioned REST API surface under `/v1`, unversioned backward-compatible aliases, a Model Context Protocol (MCP) Streamable HTTP endpoint, and an OpenAI-compatible memory proxy.

---

## 1. Interactive API Documentation

When running RecallFabric, explore the interactive documentation directly in your browser:
- **Swagger UI**: [http://localhost:8000/docs](http://localhost:8000/docs)
- **ReDoc**: [http://localhost:8000/redoc](http://localhost:8000/redoc)
- **Raw OpenAPI 3.1 Schema**: [http://localhost:8000/openapi.json](http://localhost:8000/openapi.json) or [recallfabric.openapi.json](file:///c:/Users/PC01/Desktop/Aarush/COLLEGE/Projects/capstone/openapi/recallfabric.openapi.json)

---

## 2. Core Endpoint Summary

### Task-Oriented AI Tool Surface
| Endpoint | Method | Description |
|---|---|---|
| `/v1/remember` | `POST` | Store an explicit memory or extract facts from free text (`extract=true`). |
| `/v1/recall` | `POST` | Rank and format memories with a ready-to-insert context string. |
| `/v1/forget` | `POST` | Delete by memory ID or search query with confirmation. |
| `/v1/profile` | `GET` | Retrieve the user's top durable memories and preferences. |
| `/v1/capabilities` | `GET` | Service version, vector dimensions, and supported memory types. |

### Memory CRUD & Provenance
| Endpoint | Method | Description |
|---|---|---|
| `/v1/memories` | `GET` | Paginated search and filtering of stored memories. |
| `/v1/memories` | `POST` | Create a memory with deduplication and conflict checks. |
| `/v1/memories/{id}` | `GET` | Retrieve a specific memory by UUID. |
| `/v1/memories/{id}` | `PUT` | Update content or attributes with optimistic locking. |
| `/v1/memories/{id}` | `DELETE`| Delete a memory record. |
| `/v1/memories/{id}/versions` | `GET` | Inspect version history of revisions. |
| `/v1/memories/{id}/provenance` | `GET` | Immutable audit trail of lifecycle events. |

### MCP & Non-MCP Proxy Interfaces
| Endpoint | Method | Description |
|---|---|---|
| `/mcp` | `POST` | Model Context Protocol streamable HTTP transport for remote agents. |
| `/v1/proxy/chat/completions` | `POST` | OpenAI-compatible proxy with automatic memory injection and SSE streaming. |
| `/v1/ingest` | `POST` | Webhook transcript ingestion for asynchronous background extraction. |
| `/v1/ingest/jobs/{job_id}` | `GET` | Check ingestion job status and extracted memory items. |

### User Onboarding, Auth & Data Governance
| Endpoint | Method | Description |
|---|---|---|
| `/v1/auth/signup` | `POST` | Self-serve onboarding and API key generation. |
| `/v1/auth/keys` | `GET` / `POST` | Admin listing and creation of scoped API keys. |
| `/v1/auth/keys/{id}` | `DELETE` | Revoke an existing API key. |
| `/v1/users/me/export` | `GET` | Download full machine-readable JSON data archive. |
| `/v1/users/me/memories` | `DELETE` | GDPR permanent memory deletion. |
