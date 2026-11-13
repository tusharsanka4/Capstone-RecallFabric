# Security & Privacy Model

RecallFabric is built from the ground up to protect user privacy and sensitive agent memory. This document details the security principles, cryptographic implementations, and data governance features enforced across the platform.

---

## 1. Authentication & Key Management

### API Key Generation & Hashing
- When a user signs up (`POST /v1/auth/signup`) or an admin issues a key (`POST /v1/auth/keys`), a cryptographically secure random token is generated:
  ```
  rf_live_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
  ```
- **One-Way Hashing**: Plaintext API keys are **never stored** in the database. The system stores only an HMAC-SHA256 digest (`key_hash`).
- **Constant-Time Verification**: Incoming requests are validated against stored hashes using constant-time string comparisons to eliminate timing attack vectors.
- **Tenant Scoping**: API keys are tied to a specific `user_id`. Key holders can never read, modify, or delete memories belonging to other tenants.

---

## 2. Encryption at Rest (Field-Level)

- All durable memory text contents are symmetrically encrypted before being written to PostgreSQL using AES-256 in Galois/Counter Mode (GCM) / Fernet via the cryptography engine.
- Configured via `RECALLFABRIC_ENCRYPTION_KEY`.
- If an unauthorized actor gains read access to the database or backups, raw memory text strings remain entirely unreadable without the encryption secret.

---

## 3. Upstream Credential Privacy (Memory Proxy)

When using the OpenAI-compatible proxy (`POST /v1/proxy/chat/completions`):
- Callers supply upstream LLM credentials via request headers (`X-Upstream-Key`, `X-OpenAI-Key`, or `Authorization`).
- Upstream credentials are held strictly in memory for the duration of the upstream HTTP forward.
- Upstream API keys are **strictly excluded from all logging pipelines, error messages, and audit trails**.

---

## 4. SSRF Protection & Upstream Allowlist

To prevent Server-Side Request Forgery (SSRF), the memory proxy restricts upstream forwarding destinations:
- The `X-Upstream-URL` header must match an entry in `RECALLFABRIC_PROXY_ALLOWED_UPSTREAMS`.
- Disallowed domains return `403 Forbidden` immediately before any outbound HTTP connection is initiated.

---

## 5. DoS Prevention & Rate Limiting

- **Token Bucket Limiter**: Enforces configurable requests per second (`RECALLFABRIC_RATE_LIMIT_RPS`, default: 20 rps) and burst limits (`RECALLFABRIC_RATE_LIMIT_BURST`, default: 40).
- **Request Size Capping**: HTTP request bodies are capped at `RECALLFABRIC_MAX_REQUEST_SIZE_BYTES` (default: 1 MB) to protect against memory exhaustion attacks.
- **Header-Only Logging**: Standard HTTP request logging logs method, path, status, and duration, but intentionally excludes request bodies.

---

## 6. Audit Logging & Compliance (GDPR)

- **Immutable Audit Log**: Security-relevant events (`auth_failure`, `key_created`, `key_revoked`, `export`, `bulk_delete`) are written to an append-only `audit_events` database table.
- **Right to Data Portability**: Users can download a complete machine-readable JSON archive of all memories and provenance events via `GET /v1/users/me/export`.
- **Right to be Forgotten**: Users can permanently purge all stored memories, embeddings, and version histories via `DELETE /v1/users/me/memories`.
