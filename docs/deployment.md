# Production Cloud Deployment Guide

This guide covers deploying RecallFabric to cloud platforms (Render, Fly.io, Railway) connected to a managed cloud PostgreSQL database (Neon or Supabase).

---

## Architecture Overview

RecallFabric operates as a stateless web container paired with a managed PostgreSQL instance with `pgvector` enabled:

```
+-------------------------------------------------------------+
|                 Cloud Provider (Render / Fly / Railway)     |
|                                                             |
|  +-------------------------------------------------------+  |
|  |           RecallFabric API Container (Port $PORT)    |  |
|  |   - Multi-stage UV-based Python 3.12-slim             |  |
|  |   - Pre-baked FastEmbed vector models (~130 MB)      |  |
|  |   - Multi-worker Uvicorn (FastAPI)                    |  |
|  +-------------------------------------------------------+  |
+------------------------------+------------------------------+
                               | TLS (sslmode=require)
                               v
+-------------------------------------------------------------+
|        Managed Cloud Database (Neon / Supabase)            |
|   - PostgreSQL 16+ with pgvector extension                  |
|   - Connection pooling & idle disconnect protection         |
+-------------------------------------------------------------+
```

---

## 1. Cloud Database Setup (Neon or Supabase)

### Option A: Neon (Serverless Postgres)
1. Create a project at [Neon.tech](https://neon.tech).
2. Ensure the `vector` extension is enabled (RecallFabric runs `CREATE EXTENSION IF NOT EXISTS vector` automatically on migration).
3. Copy the pooled or standard connection string:
   ```
   postgres://[user]:[password]@[neon-hostname]/neondb?sslmode=require
   ```

### Option B: Supabase
1. Create a project at [Supabase.com](https://supabase.com).
2. Navigate to **Database** -> **Extensions** -> enable `vector`.
3. Copy the transaction pooler connection URI (port 6543 or 5432) with `sslmode=require`.

---

## 2. Platform Deployments

### A. Render (One-Click with `render.yaml`)
1. Fork or push the repository to GitHub.
2. In the [Render Dashboard](https://dashboard.render.com), click **Blueprints** -> **New Blueprint Instance**.
3. Select this repository. Render automatically reads [render.yaml](file:///c:/Users/PC01/Desktop/Aarush/COLLEGE/Projects/capstone/render.yaml).
4. Supply your secrets in the environment dashboard:
   - `RECALLFABRIC_DATABASE_URL`: Your Neon/Supabase Postgres connection string.
   - `RECALLFABRIC_ADMIN_TOKEN`: A strong secret token for administrative key provisioning.
   - `RECALLFABRIC_ENCRYPTION_KEY`: A 32-byte Fernet/AES key (generate with `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`).
   - `RECALLFABRIC_OPENAI_API_KEY` (or `ANTHROPIC_API_KEY` / `GEMINI_API_KEY`): Hosted LLM API key.

### B. Fly.io (`fly.toml`)
1. Install Flyctl and authenticate:
   ```bash
   fly auth login
   ```
2. Launch the app using [fly.toml](file:///c:/Users/PC01/Desktop/Aarush/COLLEGE/Projects/capstone/fly.toml):
   ```bash
   fly launch --no-deploy
   ```
3. Set production secrets:
   ```bash
   fly secrets set \
     RECALLFABRIC_DATABASE_URL="postgres://..." \
     RECALLFABRIC_ADMIN_TOKEN="..." \
     RECALLFABRIC_ENCRYPTION_KEY="..." \
     RECALLFABRIC_OPENAI_API_KEY="sk-..."
   ```
4. Deploy:
   ```bash
   fly deploy
   ```

### C. Railway (`railway.json` / `Procfile`)
1. Create a new project in [Railway.app](https://railway.app).
2. Connect your GitHub repository.
3. In **Variables**, add all required environment variables.
4. Railway will automatically build using the multi-stage Dockerfile and execute migrations via the entrypoint script.

---

## 3. Recommended Resource Sizing

| Component | Minimum | Recommended | Notes |
|---|---|---|---|
| **RAM** | 512 MB | 1 GB - 2 GB | FastEmbed vector model requires ~250 MB in memory. |
| **CPU** | 0.5 vCPU | 1 - 2 vCPU | Faster embedding inference on batch queries. |
| **Workers** | 1 | 2 - 4 | Set `RECALLFABRIC_WORKERS=2` for production concurrency. |

> [!TIP]
> **Free-Tier Cold Starts**: On free-tier services (Render/Railway), containers spin down when idle. RecallFabric bakes the FastEmbed vector model directly into the Docker image at build time, so container spin-up takes **< 3 seconds** without downloading models over the network.
