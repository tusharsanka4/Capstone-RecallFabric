"""Protocol-level regression tests that require no database or model downloads."""

from contextlib import asynccontextmanager
from unittest.mock import MagicMock, Mock
from uuid import uuid4

import anyio
import pytest
from fastapi.testclient import TestClient
from mcp.client.session import ClientSession
from mcp.shared.memory import create_client_server_memory_streams
from sqlalchemy.exc import OperationalError

from recallfabric.core.config import Settings
from recallfabric.embeddings.service import EmbeddingUnavailable
from recallfabric.main import create_app
from recallfabric.mcp_server import (
    RecallFabricTools,
    create_mcp_server,
    current_mcp_scopes,
    require_mcp_scope,
)
from recallfabric.providers.base import ProviderUnavailable


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.parametrize("caller_session", [False, True])
def test_legacy_store_closes_only_its_own_identity_session(monkeypatch, caller_session):
    tools = RecallFabricTools(Settings(_env_file=None), engine=Mock())
    tools.remember = Mock(return_value={"memory": {"id": str(uuid4())}})
    tools._resolve_user = Mock(return_value="authenticated-owner")
    factory = MagicMock()
    monkeypatch.setattr("recallfabric.mcp_server.Session", factory)
    supplied = Mock() if caller_session else None
    result = tools.store_memory("A durable fact", session=supplied)
    assert result["user_id"] == "authenticated-owner"
    if caller_session:
        factory.assert_not_called()
        tools._resolve_user.assert_called_once_with(supplied, None)
        supplied.close.assert_not_called()
    else:
        factory.return_value.__exit__.assert_called_once()
        tools._resolve_user.assert_called_once_with(
            factory.return_value.__enter__.return_value, None
        )


@asynccontextmanager
async def connected(tools=None):
    server = create_mcp_server(Settings(_env_file=None), tools=tools)
    async with create_client_server_memory_streams() as (client, transport):
        async with anyio.create_task_group() as group:
            group.start_soon(
                server._lowlevel_server.run,
                transport[0],
                transport[1],
                server._lowlevel_server.create_initialization_options(),
            )
            async with ClientSession(*client) as session:
                await session.initialize()
                yield session
            group.cancel_scope.cancel()


@pytest.mark.anyio
async def test_tool_discovery_contract():
    async with connected() as client:
        tools = {tool.name: tool for tool in (await client.list_tools()).tools}
        assert len(tools) == 11
        for tool in tools.values():
            assert "user_id" not in tool.input_schema["properties"]
            assert tool.annotations is not None
        assert tools["forget"].annotations.destructive_hint is True
        assert tools["get_profile"].annotations.read_only_hint is True
        assert "expected_version" in tools["update_memory"].input_schema["required"]
        assert tools["recall"].input_schema["properties"]["limit"]["maximum"] == 100
        assert tools["remember"].input_schema["properties"]["importance"]["maximum"] == 1
        assert str((await client.list_resources()).resources[0].uri) == "memory://profile"
        assert (await client.get_prompt("use_memory")).messages


@pytest.mark.anyio
@pytest.mark.parametrize(
    "name,args",
    [
        ("remember", {"content": " "}),
        ("remember", {"content": "ok", "importance": 2}),
        ("remember", {"content": "ok", "type": "invalid"}),
        ("remember", {"content": "x" * 20001}),
        ("recall", {"query": "ok", "limit": 0}),
        ("recall", {"query": "ok", "limit": 101}),
        ("recall", {"query": " "}),
        ("update_memory", {"id": str(uuid4()), "content": "new"}),
        ("update_memory", {"id": "invalid", "content": "new", "expected_version": 1}),
        ("forget", {"memory_id": "invalid"}),
    ],
)
async def test_invalid_inputs_never_reach_services(name, args):
    tools = Mock()
    async with connected(tools) as client:
        result = await client.call_tool(name, args)
        assert result.is_error
        getattr(tools, name).assert_not_called()


@pytest.mark.anyio
@pytest.mark.parametrize(
    "error,code",
    [
        (EmbeddingUnavailable("private"), "EMBEDDING_UNAVAILABLE"),
        (ProviderUnavailable("private"), "PROVIDER_UNAVAILABLE"),
        (
            OperationalError("private SQL", {}, Exception("private password")),
            "DATABASE_UNAVAILABLE",
        ),
        (RuntimeError("private"), "INTERNAL_ERROR"),
    ],
)
async def test_tool_failures_are_errors_and_sanitized(error, code):
    tools = Mock()
    tools.remember.side_effect = error
    async with connected(tools) as client:
        result = await client.call_tool("remember", {"content": "test"})
        assert result.is_error
        content = " ".join(item.text for item in result.content if hasattr(item, "text"))
        assert code in content
        assert "private" not in content


@pytest.mark.parametrize("scopes", [frozenset(), frozenset({"memory:write"})])
def test_profile_rejects_missing_read_scope_before_database_access(scopes):
    token = current_mcp_scopes.set(scopes)
    try:
        tools = RecallFabricTools(Settings(_env_file=None))
        session = Mock()
        with pytest.raises(PermissionError):
            tools.get_profile(session=session, user_id="alice")
        session.execute.assert_not_called()
    finally:
        current_mcp_scopes.reset(token)


def test_api_keys_are_distinct_from_empty_oauth_scopes():
    token = current_mcp_scopes.set(None)
    try:
        require_mcp_scope("memory:read")
        require_mcp_scope("memory:write")
    finally:
        current_mcp_scopes.reset(token)


def test_extraction_failure_is_not_success(monkeypatch):
    provider = Mock()
    provider.chat.side_effect = RuntimeError("private")
    monkeypatch.setattr("recallfabric.mcp_server.get_extraction_provider", lambda _: provider)
    tools = RecallFabricTools(Settings(_env_file=None))
    with pytest.raises(ProviderUnavailable):
        tools.remember("A paragraph", extract=True, session=Mock(), user_id="alice")


def test_query_cannot_be_confirmed_without_an_explicit_target():
    tools = RecallFabricTools(Settings(_env_file=None))
    with pytest.raises(ValueError):
        tools.forget(query="something", confirm=True, session=Mock(), user_id="alice")


def test_http_dev_mode_with_key_initializes_scopes(monkeypatch):
    """Regression for the raw-key/auth-disabled branch's unbound resolved_scopes."""
    from unittest.mock import MagicMock

    session = MagicMock()
    session.__enter__.return_value = session
    session.scalar.return_value = Mock(user_id="alice")
    monkeypatch.setattr("recallfabric.main.Session", lambda *args, **kwargs: session)
    app = create_app(Settings(_env_file=None, auth_enabled=False))
    with TestClient(app) as client:
        response = client.post(
            "/mcp",
            headers={"Authorization": "Bearer test-key"},
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-11-25",
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "1"},
                },
            },
        )
        assert response.status_code == 200
        assert "capabilities" in response.text


def test_http_rejects_missing_and_revoked_keys(monkeypatch):
    from unittest.mock import MagicMock

    session = MagicMock()
    session.__enter__.return_value = session
    session.scalar.return_value = None
    monkeypatch.setattr("recallfabric.main.Session", lambda *args, **kwargs: session)
    app = create_app(Settings(_env_file=None, auth_enabled=True))
    with TestClient(app) as client:
        assert client.post("/mcp", json={}).status_code == 401
        response = client.post("/mcp", headers={"Authorization": "Bearer revoked-key"}, json={})
        assert response.status_code == 401
        assert "revoked-key" not in response.text
