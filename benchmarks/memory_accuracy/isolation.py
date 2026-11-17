"""Guarded disposable PostgreSQL schemas for benchmark scenarios."""

from __future__ import annotations

import re
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from sqlalchemy import event, text
from sqlalchemy.engine import Engine, make_url

from recallfabric.core.config import Settings
from recallfabric.db.connection import create_database_engine

SCHEMA_PATTERN = re.compile(r"^rfbench_[a-z0-9_]{8,55}$")
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


def assert_safe_target(settings: Settings, confirmed: bool) -> dict[str, str | int | None]:
    if not confirmed:
        raise RuntimeError("Refusing database benchmark without --confirm-disposable-local-db")
    if settings.environment == "production":
        raise RuntimeError("Refusing benchmark against a production environment")
    url = make_url(settings.get_database_url())
    if url.host not in LOCAL_HOSTS:
        raise RuntimeError(f"Refusing non-local database host {url.host!r}")
    database = url.database or ""
    if "prod" in database.casefold():
        raise RuntimeError(f"Refusing database with production-like name {database!r}")
    return {"host": url.host, "port": url.port, "database": database, "driver": url.drivername}


def safe_schema_name(run_id: str, scenario_id: str) -> str:
    raw = re.sub(r"[^a-z0-9]+", "_", f"rfbench_{run_id}_{scenario_id}".casefold()).strip("_")
    name = raw[:63]
    if not SCHEMA_PATTERN.fullmatch(name):
        raise RuntimeError(f"Unsafe disposable schema name {name!r}")
    return name


class DisposableSchema(AbstractContextManager[Engine]):
    """Create, migrate, and remove exactly one benchmark-owned schema."""

    def __init__(self, settings: Settings, run_id: str, scenario_id: str, *, confirmed: bool):
        self.settings = settings
        self.target = assert_safe_target(settings, confirmed)
        self.schema = safe_schema_name(run_id, scenario_id)
        self.admin: Engine | None = None
        self.engine: Engine | None = None
        self.public_count_before: int | None = None

    @staticmethod
    def _public_memory_count(engine: Engine) -> int | None:
        with engine.connect() as connection:
            exists = connection.scalar(text("SELECT to_regclass('public.memories') IS NOT NULL"))
            return (
                int(connection.scalar(text("SELECT count(*) FROM public.memories")))
                if exists
                else None
            )

    def __enter__(self) -> Engine:
        self.admin = create_database_engine(self.settings)
        self.public_count_before = self._public_memory_count(self.admin)
        with self.admin.begin() as connection:
            exists = connection.scalar(
                text("SELECT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = :name)"),
                {"name": self.schema},
            )
            if exists:
                raise RuntimeError(f"Disposable schema already exists: {self.schema}")
            connection.execute(text(f'CREATE SCHEMA "{self.schema}"'))

        self.engine = create_database_engine(self.settings)
        schema = self.schema

        @event.listens_for(self.engine, "connect")
        def set_schema(dbapi_connection: Any, _: Any) -> None:
            dbapi_connection.autocommit = True
            with dbapi_connection.cursor() as cursor:
                cursor.execute(f'SET search_path TO "{schema}", public')
            dbapi_connection.autocommit = False

        try:
            with self.engine.begin() as connection:
                config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
                config.attributes.update(connection=connection, schema=self.schema)
                command.upgrade(config, "head")
        except BaseException:
            self.__exit__(None, None, None)
            raise
        return self.engine

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        if self.engine is not None:
            self.engine.dispose()
        if self.admin is not None:
            with self.admin.begin() as connection:
                exists = connection.scalar(
                    text("SELECT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = :name)"),
                    {"name": self.schema},
                )
                if exists:
                    connection.execute(text(f'DROP SCHEMA "{self.schema}" CASCADE'))
            public_after = self._public_memory_count(self.admin)
            if public_after != self.public_count_before:
                raise RuntimeError(
                    f"Public memory count changed during isolated benchmark: "
                    f"{self.public_count_before} -> {public_after}"
                )
            self.admin.dispose()


def inspect_database(settings: Settings, confirmed: bool) -> dict[str, Any]:
    target = assert_safe_target(settings, confirmed)
    engine = create_database_engine(settings)
    try:
        with engine.connect() as connection:
            target.update(
                {
                    "server_version": connection.scalar(text("SHOW server_version")),
                    "pgvector_version": connection.scalar(
                        text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
                    ),
                    "public_memory_count": DisposableSchema._public_memory_count(engine),
                    "migration_revision": connection.scalar(
                        text("SELECT version_num FROM public.alembic_version LIMIT 1")
                    ),
                }
            )
    finally:
        engine.dispose()
    return target
