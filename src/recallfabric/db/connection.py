import logging
from typing import Any

from fastapi import Request
from sqlalchemy import Connection, Engine, create_engine, make_url, text

from recallfabric.core.config import Settings

logger = logging.getLogger(__name__)


def create_database_engine(settings: Settings) -> Engine:
    raw_url = settings.get_database_url()
    parsed_url = make_url(raw_url)

    connect_args: dict[str, Any] = {
        "connect_timeout": settings.db_connect_timeout,
        "options": "-c statement_timeout=5000",
    }
    if "sslmode" not in parsed_url.query and settings.db_sslmode:
        connect_args["sslmode"] = settings.db_sslmode

    # Never log credentials or full secret connection string.
    # Safe masked URL for debugging:
    safe_url = parsed_url.render_as_string(hide_password=True)
    logger.debug("Configuring database engine for %s", safe_url)

    return create_engine(
        parsed_url,
        pool_pre_ping=settings.db_pool_pre_ping,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_recycle=settings.db_pool_recycle,
        pool_timeout=settings.db_connect_timeout,
        connect_args=connect_args,
    )


def get_database_engine(request: Request) -> Engine:
    return request.app.state.database_engine


def database_is_ready(engine: Engine) -> bool:
    with engine.connect() as connection:
        return connection.execute(
            text("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector')")
        ).scalar_one()


def check_ssl_in_use(target: Engine | Connection) -> bool:
    """Check if the connection is currently using SSL via pg_stat_ssl."""
    query = text("SELECT ssl FROM pg_stat_ssl WHERE pid = pg_backend_pid()")
    try:
        if isinstance(target, Engine):
            with target.connect() as connection:
                res = connection.execute(query).scalar_one_or_none()
        else:
            res = target.execute(query).scalar_one_or_none()
        return bool(res)
    except Exception:
        return False
