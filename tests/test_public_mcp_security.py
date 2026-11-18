from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError
from starlette.requests import Request

from recallfabric.api.auth import (
    _issue_tokens,
    _valid_redirect_uri,
    _validate_resource,
    authorize_oauth_client,
    signup,
)
from recallfabric.core.config import Settings
from recallfabric.main import create_app
from recallfabric.schemas.auth import SignupRequest
from recallfabric.security.auth import verify_user_access


def config(**kwargs):
    return Settings(_env_file=None, mcp_public_url="https://memory.example", **kwargs)


@pytest.mark.parametrize("identity", ["victim", "existing-account", "rf_user_123"])
def test_signup_cannot_choose_an_account(identity):
    with pytest.raises(ValidationError):
        SignupRequest(user_id=identity)


def test_duplicate_signup_creates_separate_accounts():
    db = MagicMock()
    request = Request({"type": "http", "client": ("127.0.0.1", 1)})
    first = signup(SignupRequest(name="same"), request, db, config())
    second = signup(SignupRequest(name="same"), request, db, config())
    assert first.user_id != second.user_id
    assert first.api_key != second.api_key
    assert first.user_id.startswith("rf_user_")


def test_signup_disabled_even_without_auth():
    db = MagicMock()
    with pytest.raises(HTTPException) as error:
        signup(SignupRequest(), MagicMock(), db, config(allow_public_signup=False))
    assert error.value.status_code == 403
    db.add.assert_not_called()


def test_other_account_cannot_use_generated_identity():
    with pytest.raises(HTTPException) as error:
        verify_user_access("victim", SimpleNamespace(user_id="attacker"), config(auth_enabled=True))
    assert error.value.status_code == 403


def test_admin_key_issuance_requires_ownership_authority():
    with TestClient(create_app(config(auth_enabled=True))) as client:
        response = client.post("/auth/keys", json={"user_id": "victim", "name": "stolen"})
    assert response.status_code == 401


@pytest.mark.parametrize("resource", [None, "https://evil.example/mcp", "https://memory.example"])
def test_wrong_or_absent_resource_rejected(resource):
    with pytest.raises(HTTPException):
        _validate_resource(resource, config())


def test_resource_and_refresh_family_persisted():
    db = MagicMock()
    from uuid import uuid4

    family = uuid4()
    resource = _validate_resource("https://memory.example/mcp", config())
    result = _issue_tokens(db, config(), "client", "owner", "memory:read", resource, family)
    rows = [call.args[0] for call in db.add.call_args_list]
    assert all(row.resource == resource and row.user_id == "owner" for row in rows)
    assert rows[1].family_id == family
    assert result["access_token"] != rows[0].token_hash


def test_consent_escapes_client_name():
    db = MagicMock()
    db.scalar.return_value = SimpleNamespace(
        redirect_uri="https://client.example/callback", client_name='<script>alert("x")</script>'
    )
    response = authorize_oauth_client(
        db,
        config(),
        "client",
        "https://client.example/callback",
        "code",
        "a" * 43,
        "S256",
        resource="https://memory.example/mcp",
    )
    assert b"<script>" not in response.body
    assert b"&lt;script&gt;" in response.body
    assert "frame-ancestors" in response.headers["content-security-policy"]


@pytest.mark.parametrize(
    "uri",
    [
        "http://localhost.evil/cb",
        "https://a/cb#fragment",
        "https://user:pass@a/cb",
        "http://example.com/cb",
    ],
)
def test_redirect_origin_validation(uri):
    assert not _valid_redirect_uri(uri)


def test_blank_provider_falls_back_without_editing_env():
    settings = config(chat_provider="", extraction_provider=" ")
    assert settings.chat_provider is None and settings.extraction_provider is None


def test_authenticated_http_tools_use_account_context(monkeypatch):
    from recallfabric.mcp_server import current_mcp_user_id
    from recallfabric.security.auth import hash_api_key

    db = MagicMock()
    db.__enter__.return_value = db

    def lookup(statement):
        params = statement.compile().params
        if "key_hash_1" in params and params["key_hash_1"] == hash_api_key("isolated-key"):
            return SimpleNamespace(user_id="isolated-owner", key_hash="isolated-hash")
        return None

    db.scalar.side_effect = lookup
    monkeypatch.setattr("recallfabric.main.Session", lambda *args, **kwargs: db)
    app = create_app(config(auth_enabled=True))
    app.state.mcp_tools.list_memories = lambda **kwargs: [{"user_id": current_mcp_user_id.get()}]
    headers = {"Authorization": "Bearer isolated-key"}
    with TestClient(app) as client:
        init = client.post(
            "/mcp/",
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-11-25",
                    "capabilities": {},
                    "clientInfo": {"name": "isolated", "version": "1"},
                },
            },
        )
        assert init.status_code == 200
        headers["Mcp-Session-Id"] = init.headers["mcp-session-id"]
        headers["MCP-Protocol-Version"] = "2025-11-25"
        client.post(
            "/mcp/", headers=headers, json={"jsonrpc": "2.0", "method": "notifications/initialized"}
        )
        tools = client.post(
            "/mcp/", headers=headers, json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"}
        )
        assert tools.status_code == 200 and "remember" in tools.text
        result = client.post(
            "/mcp/",
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "list_memories", "arguments": {}},
            },
        )
        assert result.status_code == 200 and "isolated-owner" in result.text
        assert (
            client.post("/mcp/", headers={"Authorization": "Bearer wrong-key"}, json={}).status_code
            == 401
        )


@pytest.mark.parametrize("stored_resource", ["https://wrong.example/mcp", None])
def test_mcp_rejects_wrong_audience_token(monkeypatch, stored_resource):
    db = MagicMock()
    db.__enter__.return_value = db

    def lookup(statement):
        params = statement.compile().params
        if "resource_1" in params and params["resource_1"] == stored_resource:
            return SimpleNamespace(user_id="owner", scope="memory:read")
        return None

    db.scalar.side_effect = lookup
    monkeypatch.setattr("recallfabric.main.Session", lambda *args, **kwargs: db)
    with TestClient(create_app(config(auth_enabled=True))) as client:
        result = client.post("/mcp/", headers={"Authorization": "Bearer rf_at_wrong"}, json={})
        assert result.status_code == 401
        assert 'error="invalid_token"' in result.headers["www-authenticate"]


@pytest.mark.parametrize("stored_resource", ["https://memory.example/mcp", "https://evil/mcp"])
def test_code_exchange_checks_persisted_resource(stored_resource):
    from datetime import UTC, datetime, timedelta
    from urllib.parse import urlencode

    import anyio

    from recallfabric.api.auth import _pkce_s256, exchange_oauth_token

    verifier = "v" * 64
    db = MagicMock()
    db.scalar.return_value = SimpleNamespace(
        resource=stored_resource,
        used_at=None,
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
        client_id="client",
        redirect_uri="https://client/cb",
        code_challenge=_pkce_s256(verifier),
        user_id="verified-owner",
        scope="memory:read",
    )
    body = urlencode(
        dict(
            resource="https://memory.example/mcp",
            grant_type="authorization_code",
            client_id="client",
            redirect_uri="https://client/cb",
            code="code",
            code_verifier=verifier,
        )
    ).encode()

    async def receive():
        return {"type": "http.request", "body": body}

    request = Request({"type": "http"}, receive)
    if stored_resource != "https://memory.example/mcp":
        with pytest.raises(HTTPException):
            anyio.run(exchange_oauth_token, request, db, config())
        db.add.assert_not_called()
    else:
        result = anyio.run(exchange_oauth_token, request, db, config())
        assert result["access_token"].startswith("rf_at_")
        assert all(call.args[0].user_id == "verified-owner" for call in db.add.call_args_list)
