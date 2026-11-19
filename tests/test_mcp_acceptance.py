"""Authenticated official MCP client against real PostgreSQL in disposable schemas."""

import json
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
from recallfabric.embeddings.service import (
    EmbeddingResult,
    LocalEmbeddingProvider,
    get_embedding_provider,
)
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
                        resource=settings.oauth_resource(),
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
@pytest.mark.parametrize("credential_kind", ["api_key", "oauth"])
async def test_concurrent_tenants_cannot_read_or_mutate_each_other(database, credential_kind):
    app, engine, keys = database
    if credential_kind == "oauth":
        with Session(engine) as db, db.begin():
            for user in ("alice", "bob"):
                raw = uuid4().hex
                keys[user] = raw
                db.add(
                    OAuthAccessToken(
                        token_hash=hash_oauth_token(raw),
                        client_id="isolation-test",
                        resource=app.state.settings.oauth_resource(),
                        user_id=user,
                        scope="memory:read memory:write",
                        expires_at=datetime.now(UTC) + timedelta(hours=1),
                    )
                )
    secrets = {"alice": "Private preference ALICE_CANARY", "bob": "Private preference BOB_CANARY"}
    saved = {}
    async with app.state.mcp_server.session_manager.run():
        async with client(app, keys["alice"]) as alice, client(app, keys["bob"]) as bob:
            clients = {"alice": alice, "bob": bob}

            async def store(user):
                result = await call(clients[user], "remember", {"content": secrets[user]})
                saved[user] = result["memory"]["id"]

            async with anyio.create_task_group() as group:
                for user in clients:
                    group.start_soon(store, user)
            assert saved["alice"] != saved["bob"]

            async def attack_and_read(user, other):
                session = clients[user]
                for _ in range(3):
                    listed = await call(session, "list_memories", {})
                    assert {m["id"] for m in listed["result"]} == {saved[user]}
                    recalled = await call(session, "recall", {"query": secrets[other]})
                    assert {m["id"] for m in recalled["memories"]} <= {saved[user]}
                    profile = await call(session, "get_profile", {})
                    assert profile["memory_count"] == 1
                    assert secrets[other] not in json.dumps(profile)
                    resource = await session.read_resource("memory://profile")
                    assert secrets[other] not in resource.model_dump_json()
                history = await session.call_tool("get_memory_history", {"id": saved[other]})
                assert history.is_error or history.structured_content == {"result": []}
                for tool, args in [
                    ("get_provenance", {"id": saved[other]}),
                    (
                        "update_memory",
                        {"id": saved[other], "expected_version": 1, "content": "hijacked"},
                    ),
                    ("forget", {"memory_id": saved[other]}),
                    ("forget", {"memory_id": saved[other], "expected_version": 1, "confirm": True}),
                    ("delete_memory", {"id": saved[other], "expected_version": 1}),
                ]:
                    result = await session.call_tool(tool, args)
                    assert result.is_error, tool
                    assert secrets[other] not in result.model_dump_json()

            async with anyio.create_task_group() as group:
                group.start_soon(attack_and_read, "alice", "bob")
                group.start_soon(attack_and_read, "bob", "alice")
    with Session(engine) as db:
        rows = db.scalars(select(Memory)).all()
        assert {(m.user_id, m.content, m.version) for m in rows} == {
            (u, content, 1) for u, content in secrets.items()
        }


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
async def test_rest_and_mcp_share_memory_revisions(database):
    app, _, keys = database
    app.dependency_overrides[get_embedding_provider] = lambda: Embedder()
    async with app.state.mcp_server.session_manager.run():
        async with client(app, keys["alice"]) as mcp:
            stored = await call(mcp, "remember", {"content": "User likes Python"})
            memory_id = stored["memory"]["id"]
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://testserver",
                headers={"x-api-key": keys["alice"]},
            ) as rest:
                path = f"/memories/{memory_id}"
                current = await rest.get(path, params={"user_id": "alice"})
                assert current.status_code == 200
                assert current.json()["version"] == 1
                changed = await rest.put(
                    path,
                    params={"user_id": "alice"},
                    json={
                        "content": "User likes Rust",
                        "type": "fact",
                        "importance": 0.5,
                        "confidence": 1.0,
                        "source": "rest_test",
                        "expected_version": 1,
                    },
                )
                assert changed.status_code == 200, changed.text
                assert changed.json()["version"] == 2
                assert (
                    await mcp.call_tool(
                        "update_memory",
                        {"id": memory_id, "content": "stale", "expected_version": 1},
                    )
                ).is_error
                updated = await call(
                    mcp,
                    "update_memory",
                    {"id": memory_id, "content": "User likes Go", "expected_version": 2},
                )
                assert updated["version"] == 3
                latest = await rest.get(path, params={"user_id": "alice"})
                assert latest.json()["content"] == "User likes Go"
                assert latest.json()["version"] == 3
                provenance = await rest.get(path + "/provenance", params={"user_id": "alice"})
                assert provenance.status_code == 200
                assert len((await call(mcp, "get_provenance", {"id": memory_id}))["events"]) == len(
                    provenance.json()["events"]
                )


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
