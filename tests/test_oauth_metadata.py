from fastapi.testclient import TestClient

from recallfabric.api.auth import _pkce_s256
from recallfabric.core.config import Settings
from recallfabric.main import create_app
from recallfabric.security.auth import generate_oauth_token, hash_oauth_token


def test_protected_resource_metadata_advertises_configured_authorization_server():
    settings = Settings(
        auth_enabled=False,
        mcp_public_url="https://memory.example.com",
        oauth_authorization_server="https://login.example.com",
    )
    client = TestClient(create_app(settings))

    response = client.get("/.well-known/oauth-protected-resource")

    assert response.status_code == 200
    assert response.json() == {
        "resource": "https://memory.example.com/mcp",
        "authorization_servers": ["https://login.example.com"],
        "scopes_supported": ["memory:read", "memory:write"],
        "bearer_methods_supported": ["header"],
    }


def test_pkce_and_oauth_tokens_are_verifiable_without_persisting_plaintext():
    verifier = "a" * 64
    raw_token, token_hash = generate_oauth_token("rf_at")

    assert _pkce_s256(verifier)
    assert raw_token.startswith("rf_at_")
    assert hash_oauth_token(raw_token) == token_hash
    assert raw_token not in token_hash
