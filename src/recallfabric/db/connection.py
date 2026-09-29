"""Pooled database connections; schema management is a separate concern."""

from fastapi import Request
from sqlalchemy import URL, Engine, create_engine, text

from recallfabric.core.config import Settings


def create_database_engine(settings: Settings) -> Engine:
    url = URL.create(
        "postgresql+psycopg",
        username=settings.db_user,
        password=settings.db_password.get_secret_value(),
        host=settings.db_host,
        port=settings.db_port,
        database=settings.db_name,
    )
    return create_engine(
        url,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=5,
        pool_timeout=settings.db_connect_timeout,
        connect_args={
            "connect_timeout": settings.db_connect_timeout,
            "options": "-c statement_timeout=5000",
        },
    )


def get_database_engine(request: Request) -> Engine:
    return request.app.state.database_engine


def database_is_ready(engine: Engine) -> bool:
    with engine.connect() as connection:
        return connection.execute(
            text("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector')")
        ).scalar_one()
