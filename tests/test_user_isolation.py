import os

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from recallfabric.core.config import Settings
from recallfabric.main import create_app
from recallfabric.providers import LLMProvider, ProviderResponse

skip_without_db = pytest.mark.skipif(
    os.getenv("RECALLFABRIC_RUN_DB_TESTS") != "1",
    reason="Set RECALLFABRIC_RUN_DB_TESTS=1 for PostgreSQL API tests",
)


class MockIsolationProvider(LLMProvider):
    def is_available(self) -> bool:
        return True

    @property
    def name(self) -> str:
        return "mock"

    @property
    def model(self) -> str:
        return "mock-model"

    def chat(self, messages, temperature=0.0, max_tokens=None, json_mode=False):
        if json_mode:
            return ProviderResponse(
                '{"memories": [{"content": "User lives in Berlin", '
                '"importance": 0.8, "confidence": 0.9, "type": "fact"}]}',
                name="mock",
                model="mock-model",
            )
        return ProviderResponse(
            "Hello, this is a response.",
            name="mock",
            model="mock-model",
        )


@pytest.mark.integration
@skip_without_db
def test_comprehensive_user_isolation_across_all_endpoints():
    admin_token = "isolation-admin-token"
    settings = Settings(
        auth_enabled=True,
        admin_token=SecretStr(admin_token),
    )
    app = create_app(settings)
    app.state.chat_provider = MockIsolationProvider()
    app.state.extraction_provider = MockIsolationProvider()

    with TestClient(app) as client:
        r_key_a = client.post(
            "/auth/keys",
            json={"user_id": "user_a", "name": "key-a"},
            headers={"X-Admin-Token": admin_token},
        )
        assert r_key_a.status_code == 201
        key_a = r_key_a.json()["key"]

        r_key_b = client.post(
            "/auth/keys",
            json={"user_id": "user_b", "name": "key-b"},
            headers={"X-Admin-Token": admin_token},
        )
        assert r_key_b.status_code == 201
        key_b = r_key_b.json()["key"]

        r_b_mem = client.post(
            "/memories",
            json={
                "user_id": "user_b",
                "content": "Secret bank vault code is 49281",
                "type": "fact",
                "source": "confidential",
            },
            headers={"X-API-Key": key_b},
        )
        assert r_b_mem.status_code == 201
        b_mem_id = r_b_mem.json()["id"]

        r = client.post(
            "/memories",
            json={
                "user_id": "user_b",
                "content": "Malicious write into user_b",
                "type": "fact",
                "source": "hack",
            },
            headers={"X-API-Key": key_a},
        )
        assert r.status_code == 403

        r = client.get("/memories?user_id=user_b", headers={"X-API-Key": key_a})
        assert r.status_code == 403

        r = client.get(f"/memories/{b_mem_id}?user_id=user_b", headers={"X-API-Key": key_a})
        assert r.status_code == 403

        r = client.get(f"/memories/{b_mem_id}?user_id=user_a", headers={"X-API-Key": key_a})
        assert r.status_code == 404

        r = client.put(
            f"/memories/{b_mem_id}?user_id=user_b",
            json={
                "content": "Modified secret",
                "type": "fact",
                "source": "test",
                "expected_version": 1,
            },
            headers={"X-API-Key": key_a},
        )
        assert r.status_code == 403

        r = client.put(
            f"/memories/{b_mem_id}?user_id=user_a",
            json={
                "content": "Modified secret",
                "type": "fact",
                "source": "test",
                "expected_version": 1,
            },
            headers={"X-API-Key": key_a},
        )
        assert r.status_code == 404

        r = client.delete(f"/memories/{b_mem_id}?user_id=user_b", headers={"X-API-Key": key_a})
        assert r.status_code == 403

        r = client.delete(f"/memories/{b_mem_id}?user_id=user_a", headers={"X-API-Key": key_a})
        assert r.status_code == 404

        r = client.get(
            f"/memories/{b_mem_id}/versions?user_id=user_b", headers={"X-API-Key": key_a}
        )
        assert r.status_code == 403

        r = client.get(
            f"/memories/{b_mem_id}/versions?user_id=user_a", headers={"X-API-Key": key_a}
        )
        assert r.status_code == 404

        r = client.post(
            "/memories/search",
            json={"user_id": "user_b", "query": "vault"},
            headers={"X-API-Key": key_a},
        )
        assert r.status_code == 403

        r = client.post(
            "/memories/search",
            json={"user_id": "user_a", "query": "vault"},
            headers={"X-API-Key": key_a},
        )
        assert r.status_code == 200
        assert len(r.json()["items"]) == 0

        r = client.post(
            "/memories/retrieve",
            json={"user_id": "user_b", "query": "bank vault code", "limit": 5},
            headers={"X-API-Key": key_a},
        )
        assert r.status_code == 403

        r = client.post(
            "/memories/retrieve",
            json={"user_id": "user_a", "query": "bank vault code", "limit": 5},
            headers={"X-API-Key": key_a},
        )
        assert r.status_code == 200
        assert len(r.json()["items"]) == 0

        r = client.get(
            f"/memories/{b_mem_id}/provenance?user_id=user_b", headers={"X-API-Key": key_a}
        )
        assert r.status_code == 403

        r = client.get(
            f"/memories/{b_mem_id}/provenance?user_id=user_a", headers={"X-API-Key": key_a}
        )
        assert r.status_code == 404

        r = client.get("/provenance?user_id=user_b", headers={"X-API-Key": key_a})
        assert r.status_code == 403

        r = client.get(f"/provenance/{b_mem_id}?user_id=user_b", headers={"X-API-Key": key_a})
        assert r.status_code == 403

        r = client.post(
            "/extraction",
            json={
                "user_id": "user_b",
                "text": "I moved to Berlin yesterday",
                "source": "chat",
            },
            headers={"X-API-Key": key_a},
        )
        assert r.status_code == 403

        r = client.post(
            "/chat",
            json={"user_id": "user_b", "message": "What is my bank vault code?"},
            headers={"X-API-Key": key_a},
        )
        assert r.status_code == 403

        r = client.delete("/users/me/memories?user_id=user_b", headers={"X-API-Key": key_a})
        assert r.status_code == 403

        r = client.get("/users/me/export?user_id=user_b", headers={"X-API-Key": key_a})
        assert r.status_code == 403

        r_b_check = client.get(f"/memories/{b_mem_id}?user_id=user_b", headers={"X-API-Key": key_b})
        assert r_b_check.status_code == 200
        assert r_b_check.json()["content"] == "Secret bank vault code is 49281"
