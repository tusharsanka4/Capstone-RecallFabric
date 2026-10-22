# Stage 1: Build stage using uv for reproducible, fast dependency installation
FROM python:3.12-slim AS builder

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    RECALLFABRIC_EMBEDDING_CACHE_DIR=/app/.model-cache

WORKDIR /app

# Copy uv binary from official image
COPY --from=ghcr.io/astral-sh/uv:0.6.14 /uv /bin/uv

# Install production dependencies only (no dev dependencies)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Copy source and README to install the package wheel
COPY src ./src
COPY README.md ./
RUN uv sync --frozen --no-dev

# Bake FastEmbed model (BAAI/bge-small-en-v1.5) into the image at build time
# Containers start without downloading weights at runtime
ENV PATH="/app/.venv/bin:$PATH"
RUN python -m recallfabric.embeddings --download


# Stage 2: Minimal runtime image
FROM python:3.12-slim AS runtime

# Image size documentation:
# Base python:3.12-slim is ~130MB.
# Virtual environment with FastAPI, SQLAlchemy, psycopg, onnxruntime is ~280MB.
# Pre-baked FastEmbed model cache is ~134MB.
# Total compressed image size: ~320MB (transfer) / ~540MB (uncompressed on disk).
LABEL maintainer="RecallFabric" \
      description="Production container for RecallFabric API"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH" \
    PORT=8000 \
    RECALLFABRIC_WORKERS=1 \
    RECALLFABRIC_EMBEDDING_CACHE_DIR=/app/.model-cache

WORKDIR /app

# Install minimal curl for container healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Non-root user for production security
RUN groupadd -g 10001 appgroup && \
    useradd -u 10001 -g appgroup -s /bin/sh -d /app appuser

# Copy virtualenv and baked model cache from builder
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder --chown=appuser:appgroup /app/.model-cache /app/.model-cache

# Copy application codebase, database migrations, configuration, and entrypoint
COPY src ./src
COPY migrations ./migrations
COPY alembic.ini ./
COPY docker/entrypoint.sh ./entrypoint.sh

RUN chmod +x ./entrypoint.sh && chown -R appuser:appgroup /app

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f "http://localhost:${PORT:-8000}/health" || exit 1

ENTRYPOINT ["./entrypoint.sh"]
