"""Application factory and ASGI entry point."""

import logging
from contextlib import asynccontextmanager
from importlib.metadata import version

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from recallfabric.api.embeddings import router as embeddings_router
from recallfabric.api.health import router as health_router
from recallfabric.api.memories import router as memories_router
from recallfabric.core.config import Settings
from recallfabric.db.connection import create_database_engine
from recallfabric.embeddings.service import EmbeddingUnavailable, LocalEmbeddingProvider


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

    app.include_router(health_router)
    app.include_router(memories_router)
    app.include_router(embeddings_router)
    return app
