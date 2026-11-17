"""Authenticated official MCP client against real PostgreSQL in disposable schemas."""

import os
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import anyio
import httpx
import pytest
from alembic import command
from alembic.config import Config
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.exceptions import MCPError
from sqlalchemy import event, select, text
from sqlalchemy.orm import Session

from recallfabric.core.config import Settings
from recallfabric.db.connection import create_database_engine
from recallfabric.db.models import ApiKey, Memory, OAuthAccessToken
from recallfabric.embeddings.service import EmbeddingResult, LocalEmbeddingProvider
from recallfabric.main import create_app
from recallfabric.security.auth import generate_api_key, hash_oauth_token

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("RECALLFABRIC_RUN_DB_TESTS") != "1",
        reason="Requires local PostgreSQL",
    ),
]


@pytest.fixture
def anyio_backend():
    return "asyncio"


class Embedder:
    model_id = "acceptance-model"
    dimensions = 3

    def embed(self, content, kind="passage"):
        vector = [0, 1, 0] if content == "unrelated" else [1, 0, 0]
        return EmbeddingResult(model=self.model_id, dimensions=3, vector=vector)


@pytest.fixture
def database():
    settings = Settings(auth_enabled=True, rate_limit_burst=10000, rate_limit_rps=10000)
    admin = create_database_engine(settings)
    engine = create_database_engine(settings)
    schema = "test_mcp_" + uuid4().hex
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))

    @event.listens_for(engine, "connect")
    def set_path(connection, record):
        connection.autocommit = True
        with connection.cursor() as cursor:
            cursor.execute(f'SET search_path TO "{schema}", public')
        connection.autocommit = False

    try:
        with engine.begin() as connection:
            config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
            config.attributes.update(connection=connection, schema=schema)
            command.upgrade(config, "head")
        keys = {}
        with Session(engine) as session, session.begin():
            for user in ["alice", "bob"]:
                raw, hashed = generate_api_key()
                keys[user] = raw
                session.add(ApiKey(user_id=user, name="test", key_hash=hashed))
            for scope in ["memory:read", "memory:write", ""]:
                raw = uuid4().hex
                keys[scope] = raw
                session.add(
                    OAuthAccessToken(
                        token_hash=hash_oauth_token(raw),
                        client_id="test",
                        user_id="alice",
                        scope=scope,
                        expires_at=datetime.now(UTC) + timedelta(hours=1),
                    )
                )
        app = create_app(settings)
        app.state.database_engine = engine
        app.state.mcp_tools.engine = engine
        app.state.mcp_tools.embedder = Embedder()
        yield app, engine, keys
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


@asynccontextmanager
async def client(app, key):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
        headers={"Authorization": f"Bearer {key}"},
    ) as transport:
        async with streamable_http_client("http://testserver/mcp/", http_client=transport) as (
            reader,
            writer,
        ):
            async with ClientSession(reader, writer) as session:
                await session.initialize()
                yield session


async def call(session, tool, arguments):
    result = await session.call_tool(tool, arguments)
    assert not result.is_error, str(result.content)
    return result.structured_content


@pytest.mark.anyio
async def test_authenticated_lifecycle_and_isolation(database):
    app, engine, keys = database
    async with app.state.mcp_server.session_manager.run():
        async with client(app, keys["alice"]) as alice, client(app, keys["bob"]) as bob:
            stored = await call(alice, "remember", {"content": "User likes Python"})
            target = stored["memory"]["id"]
            recalled = await call(alice, "recall", {"query": "preferred language"})
            assert recalled["memories"][0]["id"] == target
            assert (await call(bob, "recall", {"query": "preferred language"}))["count"] == 0
            hidden = await bob.call_tool(
                "update_memory",
                {
                    "id": target,
                    "expected_version": 1,
                    "content": "stolen",
                },
            )
            assert hidden.is_error
            updated = await call(
                alice,
                "update_memory",
                {
                    "id": target,
                    "expected_version": 1,
                    "content": "User likes Rust",
                },
            )
            assert updated["version"] == 2
            assert (
                await alice.call_tool(
                    "update_memory",
                    {
                        "id": target,
                        "expected_version": 1,
                        "content": "stale",
                    },
                )
            ).is_error
            history = await call(alice, "get_memory_history", {"id": target})
            assert len(history["result"]) == 2
            assert (await call(alice, "get_provenance", {"id": target}))["events"]
            assert (await call(alice, "get_profile", {}))["memory_count"] == 1
            assert (await alice.read_resource("memory://profile")).contents
            preview = await call(alice, "forget", {"query": "preferred language"})
            assert preview["candidate"]["version"] == 2
            assert (
                await alice.call_tool(
                    "forget",
                    {
                        "memory_id": target,
                        "expected_version": 1,
                        "confirm": True,
                    },
                )
            ).is_error
            assert (await alice.call_tool("forget", {"query": "unrelated"})).is_error
            deleted = await call(
                alice,
                "forget",
                {
                    "memory_id": target,
                    "expected_version": 2,
                    "confirm": True,
                },
            )
            assert deleted["status"] == "deleted"
            assert (await call(alice, "list_memories", {}))["result"] == []
    with engine.connect() as connection:
        assert connection.execute(select(Memory.id)).all() == []


@pytest.mark.anyio
async def test_oauth_scope_boundaries(database):
    app, _, keys = database
    async with app.state.mcp_server.session_manager.run():
        async with client(app, keys["memory:read"]) as reader:
            assert (await reader.call_tool("remember", {"content": "denied"})).is_error
            assert not (await reader.call_tool("get_profile", {})).is_error
        async with client(app, keys["memory:write"]) as writer:
            assert (await writer.call_tool("get_profile", {})).is_error
            assert (await writer.call_tool("recall", {"query": "anything"})).is_error
            with pytest.raises(MCPError):
                await writer.read_resource("memory://profile")
        async with client(app, keys[""]) as empty:
            assert (await empty.call_tool("get_profile", {})).is_error
            assert (await empty.call_tool("remember", {"content": "denied"})).is_error


@pytest.mark.anyio
async def test_simultaneous_updates_one_winner(database):
    app, _, keys = database
    async with app.state.mcp_server.session_manager.run():
        async with client(app, keys["alice"]) as one, client(app, keys["alice"]) as two:
            stored = await call(one, "remember", {"content": "User likes Python"})
            target = stored["memory"]["id"]
            results = []

            async def edit(session, content):
                results.append(
                    await session.call_tool(
                        "update_memory",
                        {
                            "id": target,
                            "content": content,
                            "expected_version": 1,
                        },
                    )
                )

            async with anyio.create_task_group() as group:
                group.start_soon(edit, one, "User likes Rust")
                group.start_soon(edit, two, "User likes Go")
            assert sorted(result.is_error for result in results) == [False, True]


@pytest.mark.anyio
@pytest.mark.skipif(os.getenv("RECALLFABRIC_RUN_MODEL_TESTS") != "1", reason="Real model opt-in")
async def test_real_model_mcp_round_trip(database):
    app, _, keys = database
    app.state.mcp_tools.embedder = LocalEmbeddingProvider(Settings())
    async with app.state.mcp_server.session_manager.run():
        async with client(app, keys["alice"]) as session:
            await call(session, "remember", {"content": "User is learning Python programming"})
            response = await call(
                session, "recall", {"query": "Which programming language am I learning?"}
            )
            assert response["count"] == 1
            assert "Python" in response["memories"][0]["content"]

