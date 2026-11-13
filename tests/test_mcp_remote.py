import json
import os
import uuid
from datetime import UTC, datetime

import anyio
import pytest
from httpx import ASGITransport, AsyncClient
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.memory import create_client_server_memory_streams
from pydantic import SecretStr
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from recallfabric.core.config import Settings
from recallfabric.db.connection import create_database_engine
from recallfabric.db.models import ApiKey, AuditLog
from recallfabric.embeddings.service import LocalEmbeddingProvider
from recallfabric.main import create_app
from recallfabric.mcp_server import create_mcp_server
from recallfabric.security.auth import generate_api_key

skip_without_db = pytest.mark.skipif(
    os.getenv("RECALLFABRIC_RUN_DB_TESTS") != "1",
    reason="Set RECALLFABRIC_RUN_DB_TESTS=1 for PostgreSQL tests",
)


@skip_without_db
@pytest.mark.integration
@pytest.mark.anyio
async def test_in_memory_mcp_client_all_tools():
    """Test all 7 tools, resource, and prompt using in-memory MCP client session."""
    user_id = f"mcp_mem_{uuid.uuid4().hex[:8]}"
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

                    # 1. Verify tools list
                    tools_list = await session.list_tools()
                    tool_names = {t.name for t in tools_list.tools}
                    expected_tools = {
                        "remember",
                        "recall",
                        "forget",
                        "list_memories",
                        "update_memory",
                        "get_memory_history",
                        "get_profile",
                    }
                    assert expected_tools.issubset(tool_names)

                    # Verify docstrings/descriptions exist
                    for tool in tools_list.tools:
                        if tool.name in expected_tools:
                            assert tool.description and len(tool.description) > 10

                    # 2. Tool: remember (direct)
                    rem_res = await session.call_tool(
                        "remember",
                        {
                            "content": (
                                "User prefers FastAPI and PyDantic for modern Python microservices"
                            ),
                            "type": "preference",
                            "importance": 0.85,
                        },
                    )
                    assert not rem_res.is_error
                    rem_text = "".join(c.text for c in rem_res.content if hasattr(c, "text"))
                    assert "FastAPI" in rem_text

                    # 3. Tool: remember (extract=True)
                    rem_ext = await session.call_tool(
                        "remember",
                        {
                            "content": (
                                "My primary database is PostgreSQL 16 and I use Redis for caching."
                            ),
                            "extract": True,
                        },
                    )
                    assert not rem_ext.is_error

                    # 4. Tool: recall
                    rec_res = await session.call_tool(
                        "recall",
                        {"query": "preferred web framework and database", "limit": 5},
                    )
                    assert not rec_res.is_error
                    rec_text = "".join(c.text for c in rec_res.content if hasattr(c, "text"))
                    assert "FastAPI" in rec_text or "PostgreSQL" in rec_text

                    # 5. Tool: list_memories
                    list_res = await session.call_tool("list_memories", {"limit": 50})
                    assert not list_res.is_error
                    if list_res.structured_content and "result" in list_res.structured_content:
                        stored_memories = list_res.structured_content["result"]
                    else:
                        stored_memories = []
                        for c in list_res.content:
                            if hasattr(c, "text"):
                                try:
                                    parsed = json.loads(c.text)
                                    if isinstance(parsed, list):
                                        stored_memories.extend(parsed)
                                    elif isinstance(parsed, dict):
                                        stored_memories.append(parsed)
                                except Exception:
                                    pass
                    assert len(stored_memories) >= 1
                    target_id = stored_memories[0]["id"]

                    # 6. Tool: update_memory
                    upd_res = await session.call_tool(
                        "update_memory",
                        {
                            "id": target_id,
                            "content": "User prefers FastAPI, PyDantic v2, and async SQLAlchemy",
                            "importance": 0.95,
                        },
                    )
                    assert not upd_res.is_error
                    upd_text = "".join(c.text for c in upd_res.content if hasattr(c, "text"))
                    assert "PyDantic v2" in upd_text

                    # 7. Tool: get_memory_history
                    hist_res = await session.call_tool("get_memory_history", {"id": target_id})
                    assert not hist_res.is_error
                    hist_text = "".join(c.text for c in hist_res.content if hasattr(c, "text"))
                    assert len(hist_text) > 0

                    # 8. Tool: get_profile
                    prof_res = await session.call_tool("get_profile", {"limit": 10})
                    assert not prof_res.is_error
                    prof_text = "".join(c.text for c in prof_res.content if hasattr(c, "text"))
                    assert "Profile" in prof_text or "FastAPI" in prof_text

                    # 9. Resource: memory://profile
                    resources = await session.list_resources()
                    res_uris = [r.uri for r in resources.resources]
                    assert "memory://profile" in res_uris

                    read_prof = await session.read_resource("memory://profile")
                    prof_content = read_prof.contents[0].text
                    assert len(prof_content) > 0

                    # 10. Prompt: use_memory
                    prompts = await session.list_prompts()
                    prompt_names = [p.name for p in prompts.prompts]
                    assert "use_memory" in prompt_names

                    get_p = await session.get_prompt("use_memory", {})
                    assert len(get_p.messages) >= 1

                    # 11. Tool: forget (with semantic confirmation)
                    f_pending = await session.call_tool(
                        "forget",
                        {"query": "web framework preference", "confirm": False},
                    )
                    assert not f_pending.is_error
                    f_pending_text = "".join(
                        c.text for c in f_pending.content if hasattr(c, "text")
                    )
                    assert "pending_confirmation" in f_pending_text

                    # 12. Tool: forget (confirmed by ID)
                    f_confirmed = await session.call_tool("forget", {"memory_id": target_id})
                    assert not f_confirmed.is_error
                    f_conf_text = "".join(c.text for c in f_confirmed.content if hasattr(c, "text"))
                    assert "deleted" in f_conf_text

                tg.cancel_scope.cancel()
    finally:
        if old_env_user is not None:
            os.environ["RECALLFABRIC_USER_ID"] = old_env_user
        else:
            os.environ.pop("RECALLFABRIC_USER_ID", None)


@skip_without_db
@pytest.mark.integration
def test_remote_mcp_auth_and_audit():
    """Verify missing, invalid, and revoked API keys are rejected with 401 and logged."""
    settings = Settings(
        auth_enabled=True,
        admin_token=SecretStr("admin-test-token"),
    )
    engine = create_database_engine(settings)
    app = create_app(settings)

    user_id = f"remote_auth_{uuid.uuid4().hex[:8]}"
    raw_valid_key, hash_valid_key = generate_api_key()
    raw_revoked_key, hash_revoked_key = generate_api_key()

    with Session(engine) as sess:
        with sess.begin():
            sess.add(ApiKey(user_id=user_id, name="valid_mcp_key", key_hash=hash_valid_key))
            sess.add(
                ApiKey(
                    user_id=user_id,
                    name="revoked_mcp_key",
                    key_hash=hash_revoked_key,
                    revoked_at=datetime.now(UTC),
                )
            )

    init_payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "test-remote", "version": "1.0"},
        },
    }

    with TestClient(app) as client:
        # 1. Missing key
        res_missing = client.post("/mcp", json=init_payload)
        assert res_missing.status_code == 401
        assert "Missing API key" in res_missing.text

        # 2. Invalid key
        res_invalid = client.post(
            "/mcp",
            json=init_payload,
            headers={"Authorization": "Bearer rf_completely_bogus_key"},
        )
        assert res_invalid.status_code == 401
        assert "Invalid or revoked API key" in res_invalid.text

        # 3. Revoked key
        res_revoked = client.post(
            "/mcp",
            json=init_payload,
            headers={"Authorization": f"Bearer {raw_revoked_key}"},
        )
        assert res_revoked.status_code == 401
        assert "Invalid or revoked API key" in res_revoked.text

        # 4. Valid key -> succeeds
        res_valid = client.post(
            "/mcp",
            json=init_payload,
            headers={"Authorization": f"Bearer {raw_valid_key}"},
        )
        assert res_valid.status_code == 200
        assert "capabilities" in res_valid.text

    # Verify audit logs captured auth failures and success
    with Session(engine) as sess:
        audit_records = sess.query(AuditLog).filter(AuditLog.event_type == "auth_failure").all()
        assert len(audit_records) >= 3


@skip_without_db
@pytest.mark.integration
def test_remote_mcp_user_isolation():
    """Verify that User A's API key cannot see or modify User B's memories."""
    settings = Settings(
        auth_enabled=True,
        admin_token=SecretStr("admin-iso-token"),
    )
    engine = create_database_engine(settings)
    app = create_app(settings)

    user_a = f"iso_user_a_{uuid.uuid4().hex[:8]}"
    user_b = f"iso_user_b_{uuid.uuid4().hex[:8]}"

    raw_key_a, hash_key_a = generate_api_key()
    raw_key_b, hash_key_b = generate_api_key()

    with Session(engine) as sess:
        with sess.begin():
            sess.add(ApiKey(user_id=user_a, name="key_a", key_hash=hash_key_a))
            sess.add(ApiKey(user_id=user_b, name="key_b", key_hash=hash_key_b))

    with TestClient(app) as client:
        # User A initializes and stores a secret preference
        init_a = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "client-a", "version": "1.0"},
                },
            },
            headers={"Authorization": f"Bearer {raw_key_a}"},
        )
        assert init_a.status_code == 200
        sess_a = init_a.headers.get("mcp-session-id")
        headers_a = {"Authorization": f"Bearer {raw_key_a}"}
        if sess_a:
            headers_a["mcp-session-id"] = sess_a

        # User A stores memory
        store_a = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": "remember",
                    "arguments": {
                        "content": "SecretAlphaKey-4242 is confidential to User A",
                        "type": "fact",
                    },
                },
            },
            headers=headers_a,
        )
        assert store_a.status_code == 200
        assert "SecretAlphaKey-4242" in store_a.text

        # User B connects with User B's key
        init_b = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "client-b", "version": "1.0"},
                },
            },
            headers={"Authorization": f"Bearer {raw_key_b}"},
        )
        assert init_b.status_code == 200
        sess_b = init_b.headers.get("mcp-session-id")
        headers_b = {"Authorization": f"Bearer {raw_key_b}"}
        if sess_b:
            headers_b["mcp-session-id"] = sess_b

        # User B recalls secret query -> should NOT see User A's memory
        recall_b = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": "recall",
                    "arguments": {"query": "SecretAlphaKey-4242 confidential", "limit": 5},
                },
            },
            headers=headers_b,
        )
        assert recall_b.status_code == 200
        for line in recall_b.text.splitlines():
            if line.startswith("data: "):
                payload = json.loads(line[6:])
                struct = payload.get("result", {}).get("structuredContent", {})
                assert struct.get("memories") == []
                assert struct.get("count") == 0

        # User B lists memories -> should be empty
        list_b = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "list_memories", "arguments": {}},
            },
            headers=headers_b,
        )
        assert list_b.status_code == 200
        for line in list_b.text.splitlines():
            if line.startswith("data: "):
                payload = json.loads(line[6:])
                struct = payload.get("result", {}).get("structuredContent", {})
                assert struct.get("result") == []

        # User B cannot hijack User A's session ID with User B's key
        if sess_a:
            hijack = client.post(
                "/mcp",
                json={
                    "jsonrpc": "2.0",
                    "id": 4,
                    "method": "tools/call",
                    "params": {"name": "list_memories", "arguments": {}},
                },
                headers={"Authorization": f"Bearer {raw_key_b}", "mcp-session-id": sess_a},
            )
            assert hijack.status_code == 403


@skip_without_db
@pytest.mark.integration
@pytest.mark.anyio
async def test_remote_mcp_protocol_compliance_sdk_client():
    """Test full MCP Streamable HTTP compliance using official MCP SDK ClientSession."""
    settings = Settings(
        auth_enabled=True,
        admin_token=SecretStr("admin-sdk-token"),
    )
    engine = create_database_engine(settings)
    app = create_app(settings)

    user_id = f"remote_sdk_{uuid.uuid4().hex[:8]}"
    raw_key, hash_key = generate_api_key()

    with Session(engine) as sess:
        with sess.begin():
            sess.add(ApiKey(user_id=user_id, name="sdk_mcp_key", key_hash=hash_key))

    async with app.state.mcp_server.session_manager.run():
        app.state.database_engine = engine
        app.state.mcp_tools.engine = engine
        app.state.mcp_tools.embedder = app.state.embedding_provider

        auth_headers = {"Authorization": f"Bearer {raw_key}"}
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
            headers=auth_headers,
        ) as http_client:
            async with streamable_http_client(
                "http://testserver/mcp/",
                http_client=http_client,
            ) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    # 1. Initialize
                    init_res = await session.initialize()
                    assert init_res.protocol_version is not None

                    # 2. List tools
                    tools = await session.list_tools()
                    tool_names = [t.name for t in tools.tools]
                    assert "remember" in tool_names
                    assert "recall" in tool_names

                    # 3. Call remember
                    store_call = await session.call_tool(
                        "remember",
                        {
                            "content": "User works with Python, Rust, and TypeScript.",
                            "type": "skill",
                        },
                    )
                    assert not store_call.is_error
                    store_txt = "".join(c.text for c in store_call.content if hasattr(c, "text"))
                    assert "Python" in store_txt

                    # 4. Call recall
                    recall_call = await session.call_tool(
                        "recall",
                        {"query": "languages programming skills"},
                    )
                    assert not recall_call.is_error
                    recall_txt = "".join(c.text for c in recall_call.content if hasattr(c, "text"))
                    assert "Python" in recall_txt

                    # 5. Read profile resource
                    profile_res = await session.read_resource("memory://profile")
                    assert len(profile_res.contents) == 1
                    assert "Python" in profile_res.contents[0].text


@skip_without_db
@pytest.mark.integration
def test_remote_mcp_limits():
    """Test that rate limiting and request size limits apply to /mcp."""
    settings = Settings(
        auth_enabled=True,
        admin_token=SecretStr("admin-limit-token"),
        max_request_size_bytes=2048,
        rate_limit_rps=2.0,
        rate_limit_burst=2,
    )
    engine = create_database_engine(settings)
    app = create_app(settings)

    user_id = f"limit_user_{uuid.uuid4().hex[:8]}"
    raw_key, hash_key = generate_api_key()

    with Session(engine) as sess:
        with sess.begin():
            sess.add(ApiKey(user_id=user_id, name="limit_key", key_hash=hash_key))

    with TestClient(app) as client:
        # 1. Payload size limit check (exceeds 2048 bytes)
        huge_payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"padding": "x" * 5000},
        }
        res_huge = client.post(
            "/mcp",
            json=huge_payload,
            headers={"Authorization": f"Bearer {raw_key}"},
        )
        assert res_huge.status_code == 413
        assert "PAYLOAD_TOO_LARGE" in res_huge.text

        # 2. Rate limit check
        init_payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "test-limits", "version": "1.0"},
            },
        }
        responses = []
        for _ in range(5):
            r = client.post(
                "/mcp",
                json=init_payload,
                headers={"Authorization": f"Bearer {raw_key}"},
            )
            responses.append(r.status_code)

        assert 429 in responses
