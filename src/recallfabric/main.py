"""Application factory and ASGI entry point."""

import logging
from contextlib import asynccontextmanager
from importlib.metadata import version

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from recallfabric.api.auth import router as auth_router
from recallfabric.api.chat import router as chat_router
from recallfabric.api.embeddings import router as embeddings_router
from recallfabric.api.extraction import router as extraction_router
from recallfabric.api.health import router as health_router
from recallfabric.api.memories import router as memories_router
from recallfabric.api.provenance import router as provenance_router
from recallfabric.api.providers import router as providers_router
from recallfabric.api.users import router as users_router
from recallfabric.core.config import Settings
from recallfabric.db.connection import create_database_engine
from recallfabric.embeddings.service import EmbeddingUnavailable, LocalEmbeddingProvider
from recallfabric.providers import (
    ProviderBadResponse,
    ProviderTimeout,
    ProviderUnavailable,
)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings if settings is not None else Settings()
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        engine = create_database_engine(settings)
        app.state.database_engine = engine
        try:
            yield
        finally:
            engine.dispose()

    app = FastAPI(
        title=settings.app_name,
        description="Persistent, structured, portable memory for AI applications.",
        version=version("recallfabric"),
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.embedding_provider = LocalEmbeddingProvider(settings)

    @app.exception_handler(EmbeddingUnavailable)
    async def embedding_unavailable(request, exc):
        return JSONResponse(status_code=503, content={"detail": "Embedding model unavailable"})

    @app.exception_handler(ProviderUnavailable)
    async def provider_unavailable(request, exc):
        return JSONResponse(
            status_code=503, content={"detail": str(exc) or "LLM service unreachable"}
        )

    @app.exception_handler(ProviderTimeout)
    async def provider_timeout(request, exc):
        return JSONResponse(
            status_code=504, content={"detail": str(exc) or "LLM request timed out"}
        )

    @app.exception_handler(ProviderBadResponse)
    async def provider_bad_response(request, exc):
        return JSONResponse(status_code=502, content={"detail": str(exc) or "LLM request failed"})

    @app.middleware("http")
    async def limit_request_size(request: Request, call_next):
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                length = int(content_length)
                if length > settings.max_request_size_bytes:
                    return JSONResponse(
                        status_code=413,
                        content={"detail": "Request payload exceeds maximum allowed size"},
                    )
            except ValueError:
                pass
        return await call_next(request)

    app.include_router(health_router)
    app.include_router(auth_router)
    app.include_router(users_router)
    app.include_router(memories_router)
    app.include_router(embeddings_router)
    app.include_router(extraction_router)
    app.include_router(chat_router)
    app.include_router(provenance_router)
    app.include_router(providers_router)
    return app
