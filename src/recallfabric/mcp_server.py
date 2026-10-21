import os
from typing import Any

from mcp.server.mcpserver import MCPServer
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from recallfabric.core.config import Settings
from recallfabric.db.connection import create_database_engine
from recallfabric.db.models import ApiKey
from recallfabric.embeddings.service import EmbeddingProvider, LocalEmbeddingProvider
from recallfabric.security.auth import hash_api_key
from recallfabric.services.memory_service import (
    delete_memory_service,
    get_memory_history_service,
    list_memories_service,
    search_memory_service,
    store_memory_service,
    update_memory_service,
)


def get_authenticated_user_id(session: Session, settings: Settings) -> str:
    api_key_str = os.environ.get("RECALLFABRIC_API_KEY")
    env_user_id = os.environ.get("RECALLFABRIC_USER_ID") or settings.mcp_user_id
    if settings.auth_enabled:
        if not api_key_str:
            raise PermissionError(
                "Authentication is enabled but RECALLFABRIC_API_KEY is not configured."
            )
        hashed = hash_api_key(api_key_str)
        key_record = session.scalar(
            select(ApiKey).where(ApiKey.key_hash == hashed, ApiKey.revoked_at.is_(None))
        )
        if key_record is None:
            raise PermissionError("Invalid or revoked API key.")
        if env_user_id and env_user_id != key_record.user_id:
            raise PermissionError(
                f"User ID mismatch: configured {env_user_id} != key owner {key_record.user_id}"
            )
        return key_record.user_id

    if api_key_str:
        hashed = hash_api_key(api_key_str)
        key_record = session.scalar(
            select(ApiKey).where(ApiKey.key_hash == hashed, ApiKey.revoked_at.is_(None))
        )
        if key_record is not None:
            if env_user_id and env_user_id != key_record.user_id:
                raise PermissionError(
                    f"User ID mismatch: configured {env_user_id} != key owner {key_record.user_id}"
                )
            return key_record.user_id

    return env_user_id or "default_user"


class RecallFabricTools:
    def __init__(
        self,
        settings: Settings | None = None,
        engine: Engine | None = None,
        embedder: EmbeddingProvider | None = None,
    ):
        self.settings = settings or Settings()
        self.engine = engine or create_database_engine(self.settings)
        self.embedder = embedder or LocalEmbeddingProvider(self.settings)

    def _resolve_user(self, session: Session, user_id: str | None = None) -> str:
        if user_id is not None:
            if self.settings.auth_enabled:
                auth_user = get_authenticated_user_id(session, self.settings)
                if auth_user != user_id:
                    raise PermissionError(f"Cannot act as {user_id}; authenticated as {auth_user}")
                return auth_user
            return user_id
        return get_authenticated_user_id(session, self.settings)

    def store_memory(
        self,
        content: str,
        type: str = "fact",
        importance: float = 0.5,
        confidence: float = 1.0,
        source: str = "mcp",
        session: Session | None = None,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        if session is not None:
            uid = self._resolve_user(session, user_id)
            return store_memory_service(
                session=session,
                settings=self.settings,
                embedder=self.embedder,
                user_id=uid,
                content=content,
                type=type,
                importance=importance,
                confidence=confidence,
                source=source,
            )
        with Session(self.engine, expire_on_commit=False) as sess:
            with sess.begin():
                uid = self._resolve_user(sess, user_id)
                return store_memory_service(
                    session=sess,
                    settings=self.settings,
                    embedder=self.embedder,
                    user_id=uid,
                    content=content,
                    type=type,
                    importance=importance,
                    confidence=confidence,
                    source=source,
                )

    def search_memory(
        self,
        query: str,
        limit: int = 20,
        type: str | None = None,
        session: Session | None = None,
        user_id: str | None = None,
    ) -> list[dict[str, Any]]:
        if session is not None:
            uid = self._resolve_user(session, user_id)
            return search_memory_service(
                session=session,
                settings=self.settings,
                embedder=self.embedder,
                user_id=uid,
                query=query,
                limit=limit,
                type=type,
            )
        with Session(self.engine, expire_on_commit=False) as sess:
            with sess.begin():
                uid = self._resolve_user(sess, user_id)
                return search_memory_service(
                    session=sess,
                    settings=self.settings,
                    embedder=self.embedder,
                    user_id=uid,
                    query=query,
                    limit=limit,
                    type=type,
                )

    def update_memory(
        self,
        id: str,
        content: str,
        expected_version: int,
        session: Session | None = None,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        if session is not None:
            uid = self._resolve_user(session, user_id)
            return update_memory_service(
                session=session,
                settings=self.settings,
                embedder=self.embedder,
                user_id=uid,
                memory_id=id,
                content=content,
                expected_version=expected_version,
            )
        with Session(self.engine, expire_on_commit=False) as sess:
            with sess.begin():
                uid = self._resolve_user(sess, user_id)
                return update_memory_service(
                    session=sess,
                    settings=self.settings,
                    embedder=self.embedder,
                    user_id=uid,
                    memory_id=id,
                    content=content,
                    expected_version=expected_version,
                )

    def delete_memory(
        self,
        id: str,
        session: Session | None = None,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        if session is not None:
            uid = self._resolve_user(session, user_id)
            return delete_memory_service(
                session=session,
                settings=self.settings,
                user_id=uid,
                memory_id=id,
            )
        with Session(self.engine, expire_on_commit=False) as sess:
            with sess.begin():
                uid = self._resolve_user(sess, user_id)
                return delete_memory_service(
                    session=sess,
                    settings=self.settings,
                    user_id=uid,
                    memory_id=id,
                )

    def list_memories(
        self,
        type: str | None = None,
        status: str = "active",
        session: Session | None = None,
        user_id: str | None = None,
    ) -> list[dict[str, Any]]:
        if session is not None:
            uid = self._resolve_user(session, user_id)
            return list_memories_service(
                session=session,
                settings=self.settings,
                user_id=uid,
                type=type,
                status=status,
            )
        with Session(self.engine, expire_on_commit=False) as sess:
            with sess.begin():
                uid = self._resolve_user(sess, user_id)
                return list_memories_service(
                    session=sess,
                    settings=self.settings,
                    user_id=uid,
                    type=type,
                    status=status,
                )

    def get_memory_history(
        self,
        id: str,
        session: Session | None = None,
        user_id: str | None = None,
    ) -> list[dict[str, Any]]:
        if session is not None:
            uid = self._resolve_user(session, user_id)
            return get_memory_history_service(
                session=session,
                settings=self.settings,
                user_id=uid,
                memory_id=id,
            )
        with Session(self.engine, expire_on_commit=False) as sess:
            with sess.begin():
                uid = self._resolve_user(sess, user_id)
                return get_memory_history_service(
                    session=sess,
                    settings=self.settings,
                    user_id=uid,
                    memory_id=id,
                )


def create_mcp_server(
    settings: Settings | None = None,
    engine: Engine | None = None,
    embedder: EmbeddingProvider | None = None,
) -> MCPServer:
    settings = settings or Settings()
    tools = RecallFabricTools(settings=settings, engine=engine, embedder=embedder)
    server = MCPServer("recallfabric")

    @server.tool()
    def search_memory(
        query: str,
        limit: int = 20,
        type: str | None = None,
    ) -> list[dict[str, Any]]:
        return tools.search_memory(query=query, limit=limit, type=type)

    @server.tool()
    def store_memory(
        content: str,
        type: str = "fact",
        importance: float = 0.5,
        confidence: float = 1.0,
        source: str = "mcp",
    ) -> dict[str, Any]:
        return tools.store_memory(
            content=content,
            type=type,
            importance=importance,
            confidence=confidence,
            source=source,
        )

    @server.tool()
    def update_memory(
        id: str,
        content: str,
        expected_version: int,
    ) -> dict[str, Any]:
        return tools.update_memory(
            id=id,
            content=content,
            expected_version=expected_version,
        )

    @server.tool()
    def delete_memory(id: str) -> dict[str, Any]:
        return tools.delete_memory(id=id)

    @server.tool()
    def list_memories(
        type: str | None = None,
        status: str = "active",
    ) -> list[dict[str, Any]]:
        return tools.list_memories(type=type, status=status)

    @server.tool()
    def get_memory_history(id: str) -> list[dict[str, Any]]:
        return tools.get_memory_history(id=id)

    return server


def main() -> None:
    settings = Settings()
    server = create_mcp_server(settings)
    if settings.mcp_transport == "streamable-http":
        server.run("streamable-http", host=settings.mcp_host, port=settings.mcp_port)
    elif settings.mcp_transport == "sse":
        server.run("sse", host=settings.mcp_host, port=settings.mcp_port)
    else:
        server.run("stdio")


if __name__ == "__main__":
    main()
