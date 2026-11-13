"""Integration coverage for two independently authorized MCP clients sharing one account."""

import base64
import hashlib
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from recallfabric.core.config import Settings
from recallfabric.db.connection import create_database_engine
from recallfabric.db.models import ApiKey, OAuthAccessToken, OAuthRefreshToken
from recallfabric.main import create_app
from recallfabric.security.auth import generate_api_key

pytestmark = pytest.mark.integration


def _challenge(verifier: str) -> str:
    return (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    )


def _authorize(client: TestClient, account_key: str, client_name: str) -> dict[str, str]:
    registration = client.post(
        "/auth/oauth/register",
        json={"client_name": client_name, "redirect_uris": ["https://client.example/callback"]},
    )
    assert registration.status_code == 201
    client_id = registration.json()["client_id"]
    verifier = "v" * 64
    authorize = client.get(
        "/auth/oauth/authorize",
        params={
            "client_id": client_id,
            "redirect_uri": "https://client.example/callback",
            "response_type": "code",
            "code_challenge": _challenge(verifier),
            "code_challenge_method": "S256",
            "scope": "memory:read memory:write offline_access",
            "state": "opaque-client-state",
        },
    )
    assert authorize.status_code == 200
    request_id = authorize.text.split('name="request_id" value="')[1].split('"')[0]
    csrf = authorize.text.split('name="csrf_token" value="')[1].split('"')[0]
    approved = client.post(
        "/auth/oauth/authorize/approve",
        data={"request_id": request_id, "csrf_token": csrf, "api_key": account_key},
        follow_redirects=False,
    )
    assert approved.status_code == 303
    code = approved.headers["location"].split("code=")[1].split("&")[0]
    response = client.post(
        "/auth/oauth/token",
        data={
            "grant_type": "authorization_code",
            "client_id": client_id,
            "redirect_uri": "https://client.example/callback",
            "code": code,
            "code_verifier": verifier,
        },
    )
    assert response.status_code == 200
    return {**response.json(), "client_id": client_id}


@pytest.mark.skipif(
    os.environ.get("RECALLFABRIC_RUN_DB_TESTS") != "1",
    reason="requires isolated PostgreSQL configuration",
)
def test_two_oauth_clients_link_same_account_and_enforce_token_lifecycle():
    """Two client grants resolve to one account; other accounts and stale tokens do not."""
    settings = Settings(_env_file=None, auth_enabled=True, mcp_public_url="https://memory.example")
    engine = create_database_engine(settings)
    account = f"oauth_shared_{uuid4().hex}"
    other_account = f"oauth_other_{uuid4().hex}"
    key, key_hash = generate_api_key()
    other_key, other_hash = generate_api_key()
    try:
        with Session(engine) as db:
            db.add_all(
                [
                    ApiKey(user_id=account, name="shared", key_hash=key_hash),
                    ApiKey(user_id=other_account, name="other", key_hash=other_hash),
                ]
            )
            db.commit()
        with TestClient(create_app(settings)) as client:
            chatgpt = _authorize(client, key, "ChatGPT test client")
            claude = _authorize(client, key, "Claude test client")
            assert chatgpt["access_token"] != claude["access_token"]

            with Session(engine) as db:
                grants = db.scalars(
                    select(OAuthAccessToken).where(
                        OAuthAccessToken.client_id.in_([chatgpt["client_id"], claude["client_id"]])
                    )
                ).all()
                assert {grant.user_id for grant in grants} == {account}

            refreshed = client.post(
                "/auth/oauth/token",
                data={
                    "grant_type": "refresh_token",
                    "client_id": chatgpt["client_id"],
                    "refresh_token": chatgpt["refresh_token"],
                },
            )
            assert refreshed.status_code == 200
            assert refreshed.json()["refresh_token"] != chatgpt["refresh_token"]
            reused = client.post(
                "/auth/oauth/token",
                data={
                    "grant_type": "refresh_token",
                    "client_id": chatgpt["client_id"],
                    "refresh_token": chatgpt["refresh_token"],
                },
            )
            assert reused.status_code == 400

            invalid_pkce = client.post(
                "/auth/oauth/token",
                data={
                    "grant_type": "authorization_code",
                    "client_id": claude["client_id"],
                    "code": "not-a-code",
                    "code_verifier": "x" * 64,
                },
            )
            assert invalid_pkce.status_code == 400
            revoked = client.post("/auth/oauth/revoke", data={"token": claude["access_token"]})
            assert revoked.status_code == 204
            with Session(engine) as db:
                stale = db.scalar(
                    select(OAuthAccessToken).where(
                        OAuthAccessToken.client_id == claude["client_id"]
                    )
                )
                assert stale and stale.revoked_at is not None
                stale.expires_at = datetime.now(UTC) - timedelta(seconds=1)
                db.commit()
    finally:
        with Session(engine) as db:
            db.execute(
                delete(OAuthAccessToken).where(
                    OAuthAccessToken.user_id.in_([account, other_account])
                )
            )
            db.execute(
                delete(OAuthRefreshToken).where(
                    OAuthRefreshToken.user_id.in_([account, other_account])
                )
            )
            db.execute(delete(ApiKey).where(ApiKey.user_id.in_([account, other_account])))
            db.commit()
        engine.dispose()
