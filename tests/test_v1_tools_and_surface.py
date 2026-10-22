"""Tests for Module C3: /v1 versioned surface, AI tool endpoints,
idempotency, and OpenAPI schemas."""

from __future__ import annotations

import json
import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from recallfabric.core.config import Settings
from recallfabric.core.idempotency import default_idempotency_store
from recallfabric.embeddings.service import EmbeddingResult
from recallfabric.main import create_app
from recallfabric.providers import LLMProvider, ProviderResponse
from scripts.generate_tool_schemas import ROOT_DIR, generate_all


class MockToolProvider(LLMProvider):
    def __init__(self, name: str = "mock", model: str = "mock-model") -> None:
        self.name = name
        self.model = model

    def chat(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.0,
        max_tokens: int | None = None,
        json_mode: bool = False,
    ) -> str:
        user_msg = messages[-1].get("content", "") if messages else ""
        if "Existing memory:" in user_msg:
            return json.dumps({"classification": "unrelated", "reason": "different facts"})
        return json.dumps(
            {
                "memories": [
                    {
                        "content": "User is an engineer in Seattle working on cloud systems",
                        "type": "profile",
                        "importance": 0.8,
                        "confidence": 0.9,
                        "creation_reason": "Directly stated in conversation",
                    }
                ]
            }
        )

    def generate_sync(self, system_prompt: str, user_prompt: str, **kwargs) -> str:
        return self.chat(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ]
        )

    async def generate(self, system_prompt: str, user_prompt: str, **kwargs) -> ProviderResponse:
        return ProviderResponse(
            self.generate_sync(system_prompt, user_prompt), name=self.name, model=self.model
        )

    def is_available(self) -> bool:
        return True


class DummyDeterministicEmbedder:
    def __init__(self, dimensions: int = 4, model_id: str = "test-embedder") -> None:
        self.dimensions = dimensions
        self.model_id = model_id

    def embed(self, text: str, kind: str = "document") -> EmbeddingResult:
        vec = [float((ord(c) % 10) + 1) for c in text[: self.dimensions]]
        while len(vec) < self.dimensions:
            vec.append(1.0)
        norm = sum(x * x for x in vec) ** 0.5 or 1.0
        normalized = [x / norm for x in vec]
        return EmbeddingResult(
            vector=normalized,
            model=self.model_id,
            dimensions=self.dimensions,
        )


skip_without_db = pytest.mark.skipif(
    os.getenv("RECALLFABRIC_RUN_DB_TESTS") != "1",
    reason="Set RECALLFABRIC_RUN_DB_TESTS=1 for PostgreSQL API tests",
)


@pytest.fixture
def client(monkeypatch):
    default_idempotency_store.clear()
    settings = Settings(
        app_name="RecallFabric",
        environment="development",
        auth_enabled=False,
    )
    app = create_app(settings)
    monkeypatch.setattr(
        "recallfabric.api.v1_tools.get_extraction_provider",
        lambda s: MockToolProvider(),
    )
    with TestClient(app) as test_client:
        yield test_client


# 1. Capabilities Endpoint
def test_capabilities_endpoint(client):
    resp = client.get("/v1/capabilities")
    assert resp.status_code == 200
    data = resp.json()
    assert "service_version" in data
    assert "preference" in data["supported_memory_types"]
    assert "fact" in data["supported_memory_types"]
    assert data["embedding_dimensions"] > 0
    assert data["enabled_features"]["rate_limiting"] is True
    assert data["limits"]["context_max_chars"] == 2000


# 2. Remember Endpoint (Explicit Storage)
@skip_without_db
def test_remember_explicit_create_and_dedupe(client):
    payload = {
        "content": "User prefers dark mode in code editors and terminals.",
        "type": "preference",
        "importance": 0.85,
        "user_id": "test_user_c3",
    }
    resp = client.post("/v1/remember", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] in ("created", "stored", "deduplicated")
    assert data["memory"]["content"] == payload["content"]
    assert data["memory"]["type"] == "preference"

    # Deduplication test: re-posting identical content updates access / deduplicates
    resp2 = client.post("/v1/remember", json=payload)
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert data2["status"] in ("deduplicated", "created")


# 3. Remember Endpoint (Extraction Mode)
@skip_without_db
def test_remember_extraction_mode(client):
    payload = {
        "text": "I am an engineer in Seattle and I work on cloud distributed systems.",
        "extract": True,
        "user_id": "test_user_c3",
    }
    resp = client.post("/v1/remember", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "extracted"
    assert data["count"] >= 1
    assert len(data["memories"]) >= 1


# 4. Remember Idempotency
@skip_without_db
def test_remember_idempotency_key(client):
    idempotency_key = f"idemp-key-test-{uuid4().hex}"
    headers = {"Idempotency-Key": idempotency_key}
    payload = {
        "content": f"User is allergic to penicillin ({uuid4().hex[:6]}).",
        "type": "fact",
        "importance": 0.95,
        "user_id": "patient_1",
    }

    resp1 = client.post("/v1/remember", json=payload, headers=headers)
    assert resp1.status_code == 200
    data1 = resp1.json()
    assert "X-Idempotent-Replay" not in resp1.headers

    # Replay identical request with same Idempotency-Key
    resp2 = client.post("/v1/remember", json=payload, headers=headers)
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert resp2.headers.get("x-idempotent-replay") == "true"
    assert data2["memory"]["id"] == data1["memory"]["id"]


# 5. Recall Endpoint (Ranked Context)
@skip_without_db
def test_recall_and_context_budget(client):
    user_id = f"recall_tester_{uuid4().hex[:6]}"
    client.post(
        "/v1/remember",
        json={"content": "User loves Python and FastAPI", "type": "preference", "user_id": user_id},
    )
    client.post(
        "/v1/remember",
        json={"content": "User lives in New York City", "type": "fact", "user_id": user_id},
    )

    resp = client.post(
        "/v1/recall",
        json={"query": "What programming languages does the user like?", "user_id": user_id},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] >= 1
    assert "context" in data
    assert "- [" in data["context"]
    assert len(data["memories"]) >= 1
    assert "score" in data["memories"][0]


# 6. Forget Endpoint (Direct by ID and Query with Confirmation)
@skip_without_db
def test_forget_endpoint_flow(client):
    user_id = f"forget_user_{uuid4().hex[:6]}"
    mem_resp = client.post(
        "/v1/remember",
        json={
            "content": "User used to play tennis every Sunday",
            "type": "fact",
            "user_id": user_id,
        },
    )
    mem_id = mem_resp.json()["memory"]["id"]

    # Query search without confirm -> returns candidate awaiting confirmation
    resp_pending = client.post(
        "/v1/forget",
        json={"query": "tennis", "confirm": False, "user_id": user_id},
    )
    assert resp_pending.status_code == 200
    data_p = resp_pending.json()
    assert data_p["confirmed"] is False
    assert data_p["status"] == "pending_confirmation"
    assert data_p["candidate"]["id"] == mem_id

    # Query search with confirm=true -> deletes
    resp_del = client.post(
        "/v1/forget",
        json={"query": "tennis", "confirm": True, "user_id": user_id},
    )
    assert resp_del.status_code == 200
    data_d = resp_del.json()
    assert data_d["confirmed"] is True
    assert data_d["status"] == "deleted"
    assert data_d["deleted_id"] == mem_id

    # Verify deleted by id
    mem2_resp = client.post(
        "/v1/remember",
        json={"content": "User likes basketball", "type": "fact", "user_id": user_id},
    )
    mem2_id = mem2_resp.json()["memory"]["id"]
    resp_by_id = client.post(
        "/v1/forget",
        json={"memory_id": mem2_id, "user_id": user_id},
    )
    assert resp_by_id.status_code == 200
    assert resp_by_id.json()["confirmed"] is True
    assert resp_by_id.json()["deleted_id"] == mem2_id


# 7. Profile Endpoint
@skip_without_db
def test_profile_endpoint(client):
    user_id = f"profile_user_{uuid4().hex[:6]}"
    client.post(
        "/v1/remember",
        json={
            "content": "Staff Architect at TechCorp",
            "type": "profile",
            "importance": 0.9,
            "user_id": user_id,
        },
    )
    client.post(
        "/v1/remember",
        json={
            "content": "Prefers asynchronous communication",
            "type": "preference",
            "importance": 0.8,
            "user_id": user_id,
        },
    )

    resp = client.get("/v1/profile", params={"user_id": user_id})
    assert resp.status_code == 200
    data = resp.json()
    assert data["user_id"] == user_id
    assert data["memory_count"] == 2
    assert "Staff Architect" in data["summary"]
    assert "profile" in data["categories"]
    assert "preference" in data["categories"]


# 8. Consistent Error Envelope on /v1
def test_v1_error_format_vs_unversioned(client):
    # /v1 validation error returns {error: {code, message}}
    resp_v1_val = client.post("/v1/remember", json={})
    assert resp_v1_val.status_code == 422
    assert "error" in resp_v1_val.json()
    assert resp_v1_val.json()["error"]["code"] == "VALIDATION_ERROR"
    assert "message" in resp_v1_val.json()["error"]

    # /v1 404 returns {error: {code, message}}
    fake_id = str(uuid4())
    resp_v1_404 = client.get(f"/v1/memories/{fake_id}", params={"user_id": "any"})
    assert resp_v1_404.status_code == 404
    assert "error" in resp_v1_404.json()
    assert resp_v1_404.json()["error"]["code"] == "NOT_FOUND"

    # Unversioned route returns {detail: ...} for backward compatibility
    resp_legacy_404 = client.get(f"/memories/{fake_id}", params={"user_id": "any"})
    assert resp_legacy_404.status_code == 404
    assert "detail" in resp_legacy_404.json()
    assert "error" not in resp_legacy_404.json()


# 9. Unversioned Working Route Aliases
@skip_without_db
def test_unversioned_route_aliases(client):
    # Unversioned /memories POST
    resp = client.post(
        "/memories",
        json={
            "content": f"Alias test memory {uuid4().hex[:6]}",
            "type": "fact",
            "source": "alias_test",
            "user_id": "alias_user",
        },
    )
    assert resp.status_code == 201
    mem_id = resp.json()["id"]

    # Unversioned /memories GET
    resp_get = client.get(f"/memories/{mem_id}", params={"user_id": "alias_user"})
    assert resp_get.status_code == 200
    assert "Alias test memory" in resp_get.json()["content"]

    # Health check
    assert client.get("/health").json() == {"status": "ok"}


# 10. Auth Scoping Tests
@skip_without_db
def test_auth_scoping_on_v1(monkeypatch):
    admin_token_str = "admin_secret_token_123"
    settings = Settings(
        app_name="RecallFabric",
        environment="development",
        auth_enabled=True,
        admin_token=admin_token_str,
    )
    app = create_app(settings)
    monkeypatch.setattr(
        "recallfabric.api.v1_tools.get_extraction_provider",
        lambda s: MockToolProvider(),
    )

    with TestClient(app) as test_client:
        # Create Alice key via admin endpoint
        alice_key_resp = test_client.post(
            "/v1/auth/keys",
            json={"user_id": "alice_scoped", "name": "alice-scoped-key"},
            headers={"Authorization": f"Bearer {admin_token_str}"},
        )
        assert alice_key_resp.status_code == 201
        raw_key_alice = alice_key_resp.json()["key"]

        # Create Bob key via admin endpoint
        bob_key_resp = test_client.post(
            "/v1/auth/keys",
            json={"user_id": "bob_scoped", "name": "bob-scoped-key"},
            headers={"Authorization": f"Bearer {admin_token_str}"},
        )
        assert bob_key_resp.status_code == 201
        raw_key_bob = bob_key_resp.json()["key"]

        # 1. Alice creates a memory
        resp = test_client.post(
            "/v1/remember",
            json={"content": "Alice's secret plans", "type": "fact"},
            headers={"Authorization": f"Bearer {raw_key_alice}"},
        )
        assert resp.status_code == 200
        alice_mem_id = resp.json()["memory"]["id"]

        # 2. Alice accessing her memory via profile works
        resp_prof = test_client.get(
            "/v1/profile",
            headers={"Authorization": f"Bearer {raw_key_alice}"},
        )
        assert resp_prof.status_code == 200
        assert resp_prof.json()["user_id"] == "alice_scoped"

        # 3. Alice trying to spoof user_id as bob fails with 403
        resp_spoof = test_client.post(
            "/v1/remember",
            json={"content": "Trying to write to Bob's profile", "user_id": "bob_scoped"},
            headers={"Authorization": f"Bearer {raw_key_alice}"},
        )
        assert resp_spoof.status_code == 403

        # 4. Bob cannot recall or forget Alice's memory
        resp_recall = test_client.post(
            "/v1/recall",
            json={"query": "secret plans"},
            headers={"Authorization": f"Bearer {raw_key_bob}"},
        )
        assert resp_recall.status_code == 200
        assert resp_recall.json()["count"] == 0

        resp_forget = test_client.post(
            "/v1/forget",
            json={"memory_id": alice_mem_id},
            headers={"Authorization": f"Bearer {raw_key_bob}"},
        )
        # Cannot delete alice's memory
        assert resp_forget.status_code in (404, 422, 403)


# 11. Schema Drift Test
def test_schema_drift():
    """Fail if openapi/recallfabric.openapi.json or tools/*.json are missing or stale."""
    generated = generate_all()
    for path, expected_content in generated.items():
        assert path.is_file(), f"Missing schema file: {path.relative_to(ROOT_DIR)}"
        actual_content = path.read_text(encoding="utf-8")
        assert actual_content == expected_content, (
            f"Schema drift in {path.relative_to(ROOT_DIR)}! "
            "Run 'python scripts/generate_tool_schemas.py' to update."
        )


# 12. Acceptance Test: LLM Calling Tools via tools/openai_tools.json
@skip_without_db
def test_llm_tool_calling_acceptance(client):
    """An LLM given tools/openai_tools.json can call remember and recall successfully."""
    tools_file = ROOT_DIR / "tools" / "openai_tools.json"
    assert tools_file.is_file()
    openai_tools = json.loads(tools_file.read_text(encoding="utf-8"))

    # Verify tool definitions exist
    tool_names = [t["function"]["name"] for t in openai_tools if t.get("type") == "function"]
    assert "remember" in tool_names
    assert "recall" in tool_names
    assert "forget" in tool_names

    user_id = f"llm_agent_user_{uuid4().hex[:6]}"
    # Simulated LLM function call arguments for remember
    llm_remember_call = {
        "content": "User prefers pytest for unit testing and prefers short functions.",
        "type": "preference",
        "importance": 0.9,
        "user_id": user_id,
    }
    remember_resp = client.post("/v1/remember", json=llm_remember_call)
    assert remember_resp.status_code == 200
    rem_data = remember_resp.json()
    assert rem_data["status"] in ("created", "stored", "deduplicated")

    # Simulated LLM function call arguments for recall
    llm_recall_call = {
        "query": "What unit testing framework does the user prefer?",
        "limit": 3,
        "user_id": user_id,
    }
    recall_resp = client.post("/v1/recall", json=llm_recall_call)
    assert recall_resp.status_code == 200
    rec_data = recall_resp.json()
    assert rec_data["count"] >= 1
    assert "pytest" in rec_data["context"]
