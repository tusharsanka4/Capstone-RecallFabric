from datetime import UTC, datetime, timedelta
from html import unescape
from types import SimpleNamespace
from unittest.mock import MagicMock
from urllib.parse import parse_qs, urljoin, urlsplit
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from recallfabric.api.auth import router
from recallfabric.core.config import Settings, get_settings
from recallfabric.db.session import get_session


def test_same_origin_consent_and_callback_behind_https_proxy():
    origin = "https://tunnel.example"
    db = MagicMock()
    transaction = SimpleNamespace(
        id=uuid4(),
        csrf_token="csrf-proof",
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
        approved_at=None,
        client_id="client",
        redirect_uri="https://chatgpt.com/callback?existing=1",
        code_challenge="a" * 43,
        scope="memory:read",
        resource=origin + "/mcp",
        state="state-proof",
    )
    registered = SimpleNamespace(client_name="ChatGPT", redirect_uri=transaction.redirect_uri)
    db.scalar.side_effect = [registered, transaction, SimpleNamespace(user_id="verified-owner")]
    app = FastAPI()
    app.add_middleware(ProxyHeadersMiddleware, trusted_hosts="127.0.0.1")
    app.include_router(router)
    app.dependency_overrides[get_session] = lambda: db
    observed_origins = []

    def settings(request: Request):
        observed_origins.append(str(request.base_url))
        return Settings(_env_file=None, mcp_public_url=origin, auth_enabled=True)

    app.dependency_overrides[get_settings] = settings
    with TestClient(app, base_url="http://tunnel.example", client=("127.0.0.1", 1)) as client:
        consent = client.get(
            "/auth/oauth/authorize",
            params={
                "client_id": "client",
                "redirect_uri": transaction.redirect_uri,
                "response_type": "code",
                "code_challenge": "a" * 43,
                "code_challenge_method": "S256",
                "resource": origin + "/mcp",
            },
            headers={"X-Forwarded-Proto": "https", "X-Forwarded-For": "203.0.113.1"},
        )
        assert consent.status_code == 200
        assert 'action="/auth/oauth/authorize/approve"' in consent.text
        assert (
            urlsplit(urljoin(str(consent.url), "/auth/oauth/authorize/approve")).netloc
            == "tunnel.example"
        )
        assert "form-action 'self'" in consent.headers["content-security-policy"]
        approved = client.post(
            "/auth/oauth/authorize/approve",
            data={
                "request_id": str(transaction.id),
                "csrf_token": transaction.csrf_token,
                "api_key": "existing-account-proof",
            },
        )
    assert observed_origins[0] == origin + "/"
    assert approved.status_code == 200
    assert "location" not in approved.headers  # No cross-origin form redirect chain.
    assert "form-action 'self'" in approved.headers["content-security-policy"]
    assert approved.headers["referrer-policy"] == "no-referrer"
    assert 'http-equiv="refresh"' in approved.text
    callback = unescape(approved.text.split('href="')[1].split('"')[0])
    assert urlsplit(callback).netloc == "chatgpt.com"
    params = parse_qs(urlsplit(callback).query)
    assert params["state"] == ["state-proof"] and params["existing"] == ["1"]
    assert params["code"][0].startswith("rf_code_")
    assert transaction.approved_at is not None
