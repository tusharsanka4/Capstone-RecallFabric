import os
import uuid

import anyio
import pytest
from mcp.client.session import ClientSession
from mcp.shared.memory import create_client_server_memory_streams
from pydantic import SecretStr
from sqlalchemy.orm import Session

from recallfabric.core.config import Settings
from recallfabric.db.connection import create_database_engine
from recallfabric.db.models import ApiKey
from recallfabric.embeddings.service import LocalEmbeddingProvider
from recallfabric.mcp_server import RecallFabricTools, create_mcp_server
from recallfabric.security.auth import generate_api_key

skip_without_db = pytest.mark.skipif(
    os.getenv("RECALLFABRIC_RUN_DB_TESTS") != "1",
    reason="Set RECALLFABRIC_RUN_DB_TESTS=1 for PostgreSQL API tests",
)


@skip_without_db
@pytest.mark.integration
def test_mcp_tools_unit_with_session():
    settings = Settings(auth_enabled=False)
    engine = create_database_engine(settings)
    embedder = LocalEmbeddingProvider(settings)
    tools = RecallFabricTools(settings=settings, engine=engine, embedder=embedder)

    user_id = f"mcp_unit_{uuid.uuid4().hex[:8]}"

    with Session(engine, expire_on_commit=False) as session:
        with session.begin():
            stored = tools.store_memory(
                content="User is learning Rust",
                type="skill",
                importance=0.8,
                confidence=0.9,
                session=session,
                user_id=user_id,
            )
            assert stored["content"] == "User is learning Rust"
            assert stored["type"] == "skill"
            assert stored["version"] == 1
            mem_id = stored["id"]

    with Session(engine, expire_on_commit=False) as session:
        with session.begin():
            found = tools.search_memory(
                query="what is the user learning",
                session=session,
                user_id=user_id,
            )
            assert len(found) >= 1
            assert any("User is learning Rust" in item["content"] for item in found)

    with Session(engine, expire_on_commit=False) as session:
        with session.begin():
            listed = tools.list_memories(session=session, user_id=user_id)
            assert len(listed) >= 1
            assert any(item["id"] == mem_id for item in listed)

    with Session(engine, expire_on_commit=False) as session:
        with session.begin():
            history = tools.get_memory_history(id=mem_id, session=session, user_id=user_id)
            assert len(history) == 1
            assert history[0]["version"] == 1

    with Session(engine, expire_on_commit=False) as session:
        with session.begin():
            updated = tools.update_memory(
                id=mem_id,
                content="User is mastering Rust async",
                expected_version=1,
                session=session,
                user_id=user_id,
            )
            assert updated["version"] == 2
            assert updated["content"] == "User is mastering Rust async"

    with Session(engine, expire_on_commit=False) as session:
        with session.begin():
            history_after = tools.get_memory_history(id=mem_id, session=session, user_id=user_id)
            assert len(history_after) == 2

    with Session(engine, expire_on_commit=False) as session:
        with session.begin():
            del_res = tools.delete_memory(id=mem_id, session=session, user_id=user_id)
            assert del_res["deleted"] is True

    with Session(engine, expire_on_commit=False) as session:
        with session.begin():
            active_after = tools.list_memories(session=session, user_id=user_id)
            assert not any(item["id"] == mem_id for item in active_after)


@skip_without_db
@pytest.mark.integration
def test_mcp_auth_model():
    settings = Settings(
        auth_enabled=True,
        admin_token=SecretStr("mcp-test-admin"),
    )
    engine = create_database_engine(settings)
    embedder = LocalEmbeddingProvider(settings)
    tools = RecallFabricTools(settings=settings, engine=engine, embedder=embedder)

    owner_user = f"mcp_auth_{uuid.uuid4().hex[:8]}"
    raw_key, key_hash = generate_api_key()

    with Session(engine) as session:
        with session.begin():
            db_key = ApiKey(
                user_id=owner_user,
                name="mcp-test-key",
                key_hash=key_hash,
            )
            session.add(db_key)

    old_env_key = os.environ.get("RECALLFABRIC_API_KEY")
    old_env_user = os.environ.get("RECALLFABRIC_USER_ID")

    try:
        os.environ.pop("RECALLFABRIC_API_KEY", None)
        os.environ.pop("RECALLFABRIC_USER_ID", None)

        with pytest.raises(PermissionError):
            with Session(engine, expire_on_commit=False) as session:
                with session.begin():
                    tools.store_memory(
                        content="Should fail without key",
                        session=session,
                    )

        os.environ["RECALLFABRIC_API_KEY"] = "rf_invalid_key_123"
        with pytest.raises(PermissionError):
            with Session(engine, expire_on_commit=False) as session:
                with session.begin():
                    tools.store_memory(
                        content="Should fail with bad key",
                        session=session,
                    )

        os.environ["RECALLFABRIC_API_KEY"] = raw_key
        os.environ["RECALLFABRIC_USER_ID"] = "different_user"
        with pytest.raises(PermissionError):
            with Session(engine, expire_on_commit=False) as session:
                with session.begin():
                    tools.store_memory(
                        content="Should fail with mismatched user",
                        session=session,
                    )

        os.environ["RECALLFABRIC_USER_ID"] = owner_user
        with Session(engine, expire_on_commit=False) as session:
            with session.begin():
                res = tools.store_memory(
                    content="Valid authenticated memory",
                    session=session,
                )
                assert res["user_id"] == owner_user
                assert res["content"] == "Valid authenticated memory"
    finally:
        if old_env_key is not None:
            os.environ["RECALLFABRIC_API_KEY"] = old_env_key
        else:
            os.environ.pop("RECALLFABRIC_API_KEY", None)
        if old_env_user is not None:
            os.environ["RECALLFABRIC_USER_ID"] = old_env_user
        else:
            os.environ.pop("RECALLFABRIC_USER_ID", None)


@skip_without_db
@pytest.mark.integration
@pytest.mark.anyio
async def test_mcp_in_memory_client_integration():
    user_id = f"mcp_client_{uuid.uuid4().hex[:8]}"
    old_env_user = os.environ.get("RECALLFABRIC_USER_ID")
    os.environ["RECALLFABRIC_USER_ID"] = user_id

    try:
        settings = Settings(auth_enabled=False)
        engine = create_database_engine(settings)
        embedder = LocalEmbeddingProvider(settings)
        server = create_mcp_server(settings=settings, engine=engine, embedder=embedder)

        async with create_client_server_memory_streams() as (client_streams, server_streams):
            async with anyio.create_task_group() as tg:
                tg.start_soon(
                    server._lowlevel_server.run,
                    server_streams[0],
                    server_streams[1],
                    server._lowlevel_server.create_initialization_options(),
                )
                async with ClientSession(client_streams[0], client_streams[1]) as session:
                    await session.initialize()

                    tools_list = await session.list_tools()
                    tool_names = [t.name for t in tools_list.tools]
                    assert "store_memory" in tool_names
                    assert "search_memory" in tool_names
                    assert "update_memory" in tool_names
                    assert "delete_memory" in tool_names
                    assert "list_memories" in tool_names
                    assert "get_memory_history" in tool_names

                    store_res = await session.call_tool(
                        "store_memory",
                        {"content": "User is learning Rust", "type": "skill"},
                    )
                    assert not store_res.is_error
                    res_text = "".join(c.text for c in store_res.content if hasattr(c, "text"))
                    assert "User is learning Rust" in res_text

                    search_res = await session.call_tool(
                        "search_memory",
                        {"query": "what is the user learning"},
                    )
                    assert not search_res.is_error
                    search_text = "".join(c.text for c in search_res.content if hasattr(c, "text"))
                    assert "User is learning Rust" in search_text

                tg.cancel_scope.cancel()
    finally:
        if old_env_user is not None:
            os.environ["RECALLFABRIC_USER_ID"] = old_env_user
        else:
            os.environ.pop("RECALLFABRIC_USER_ID", None)
