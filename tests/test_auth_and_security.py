import os
import uuid

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import select

from recallfabric.core.config import Settings
from recallfabric.db.models import Memory
from recallfabric.main import create_app
from recallfabric.providers import LLMProvider, ProviderResponse
from recallfabric.security.encryption import decrypt_content, encrypt_content
from recallfabric.security.rate_limiter import rate_limiter

skip_without_db = pytest.mark.skipif(
    os.getenv("RECALLFABRIC_RUN_DB_TESTS") != "1",
    reason="Set RECALLFABRIC_RUN_DB_TESTS=1 for PostgreSQL API tests",
)


class MockProvider(LLMProvider):
    def __init__(self, name: str = "mock", model: str = "mock-model"):
        self._name = name
        self._model = model

    @property
    def name(self) -> str:
        return self._name

    @property
    def model(self) -> str:
        return self._model

    def is_available(self) -> bool:
        return True

    def chat(self, messages, temperature=0.0, max_tokens=None, json_mode=False):
        return ProviderResponse(
            '{"memories": [{"content": "User loves Python", '
            '"importance": 0.8, "confidence": 0.9, "type": "skill"}]}',
            name=self._name,
            model=self._model,
        )


def test_encryption_roundtrip():
    key = Fernet.generate_key().decode("utf-8")
    original = "User prefers dark mode and vim keybindings"
    encrypted = encrypt_content(original, key)
    assert encrypted.startswith("enc::")
    assert encrypted != original
    decrypted = decrypt_content(encrypted, key)
    assert decrypted == original


@skip_without_db
def test_auth_disabled_backward_compatibility():
    settings = Settings(auth_enabled=False)
    app = create_app(settings)
    with TestClient(app) as client:
        r = client.post("/auth/keys", json={"user_id": "alice", "name": "test-key"})
        assert r.status_code == 401

        r = client.get("/memories?user_id=alice")
        assert r.status_code == 200


@skip_without_db
@pytest.mark.integration
def test_admin_key_lifecycle():
    admin_token = "secret-admin-123"
    settings = Settings(
        auth_enabled=True,
        admin_token=SecretStr(admin_token),
    )
    app = create_app(settings)

    with TestClient(app) as client:
        r = client.post("/auth/keys", json={"user_id": "alice", "name": "alice-laptop"})
        assert r.status_code == 401

        r = client.post(
            "/auth/keys",
            json={"user_id": "alice", "name": "alice-laptop"},
            headers={"X-Admin-Token": "wrong-token"},
        )
        assert r.status_code == 401

        r = client.post(
            "/auth/keys",
            json={"user_id": "alice", "name": "alice-laptop"},
            headers={"X-Admin-Token": admin_token},
        )
        assert r.status_code == 201
        data = r.json()
        raw_key = data["key"]
        key_id = data["id"]
        assert raw_key.startswith("rf_")
        assert data["user_id"] == "alice"
        assert data["name"] == "alice-laptop"

        r = client.get("/auth/keys", headers={"X-Admin-Token": admin_token})
        assert r.status_code == 200
        keys = r.json()
        assert any(k["id"] == key_id for k in keys)
        for k in keys:
            assert "key" not in k
            assert "key_hash" not in k

        r = client.delete(f"/auth/keys/{key_id}", headers={"X-Admin-Token": admin_token})
        assert r.status_code == 204

        r = client.get("/memories?user_id=alice", headers={"X-API-Key": raw_key})
        assert r.status_code == 401


@skip_without_db
@pytest.mark.integration
def test_auth_enabled_user_operations_and_auditing():
    admin_token = "admin-secret-999"
    settings = Settings(
        auth_enabled=True,
        admin_token=SecretStr(admin_token),
    )
    app = create_app(settings)

    with TestClient(app) as client:
        r_create = client.post(
            "/auth/keys",
            json={"user_id": "alice", "name": "alice-key"},
            headers={"X-Admin-Token": admin_token},
        )
        assert r_create.status_code == 201
        alice_key = r_create.json()["key"]

        r_unauth = client.get("/memories?user_id=alice")
        assert r_unauth.status_code == 401
        assert "secret" not in r_unauth.text.lower()

        r_mismatch = client.get("/memories?user_id=bob", headers={"X-API-Key": alice_key})
        assert r_mismatch.status_code == 403

        r_mem = client.post(
            "/memories",
            json={
                "user_id": "alice",
                "content": "User speaks French and Spanish",
                "type": "skill",
                "source": "onboarding",
            },
            headers={"X-API-Key": alice_key},
        )
        assert r_mem.status_code == 201
        mem_id = r_mem.json()["id"]

        r_export = client.get("/users/me/export", headers={"X-API-Key": alice_key})
        assert r_export.status_code == 200
        export_data = r_export.json()
        assert export_data["user_id"] == "alice"
        assert len(export_data["memories"]) >= 1
        assert any(m["id"] == mem_id for m in export_data["memories"])

        r_delete_all = client.delete("/users/me/memories", headers={"X-API-Key": alice_key})
        assert r_delete_all.status_code == 200
        assert r_delete_all.json()["deleted_memories"] >= 1

        r_list = client.get("/memories?user_id=alice", headers={"X-API-Key": alice_key})
        assert r_list.status_code == 200
        assert len(r_list.json()["items"]) == 0


def test_rate_limiting():
    rate_limiter.reset()
    assert rate_limiter.check_rate_limit("test-key", 2.0, 2) is True
    assert rate_limiter.check_rate_limit("test-key", 2.0, 2) is True
    assert rate_limiter.check_rate_limit("test-key", 2.0, 2) is False


def test_request_size_limit():
    settings = Settings(
        max_request_size_bytes=1024,
    )
    app = create_app(settings)
    with TestClient(app) as client:
        r = client.post(
            "/memories/search",
            headers={"Content-Length": "2000"},
            json={"user_id": "alice", "query": "hello" * 50},
        )
        assert r.status_code == 413


@skip_without_db
@pytest.mark.integration
def test_field_level_encryption_at_rest():
    fernet_key = Fernet.generate_key().decode("utf-8")
    settings = Settings(
        auth_enabled=False,
        encryption_key=SecretStr(fernet_key),
    )
    app = create_app(settings)

    with TestClient(app) as client:
        user_id = f"patient_{uuid.uuid4().hex[:8]}"
        content = "User has an allergic reaction to peanuts"
        r_create = client.post(
            "/memories",
            json={
                "user_id": user_id,
                "content": content,
                "type": "fact",
                "source": "medical_intake",
            },
        )
        assert r_create.status_code == 201
        created_data = r_create.json()
        assert created_data["content"] == content
        mem_id = created_data["id"]

        engine = app.state.database_engine
        from sqlalchemy.orm import Session

        with Session(engine) as session:
            db_row = session.scalar(select(Memory).where(Memory.id == mem_id))
            assert db_row is not None
            assert db_row.content.startswith("enc::")
            assert content not in db_row.content

        r_read = client.get(f"/memories/{mem_id}?user_id={user_id}")
        assert r_read.status_code == 200
        assert r_read.json()["content"] == content

        r_retrieve = client.post(
            "/memories/retrieve",
            json={
                "user_id": user_id,
                "query": "peanuts allergy",
                "limit": 5,
            },
        )
        assert r_retrieve.status_code == 200
        items = r_retrieve.json()["items"]
        assert len(items) >= 1
        assert items[0]["content"] == content
