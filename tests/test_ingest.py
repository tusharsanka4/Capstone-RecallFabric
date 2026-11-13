"""Tests for Module C6: Webhook transcript ingestion and async jobs."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from recallfabric.core.config import Settings
from recallfabric.main import create_app
from recallfabric.providers import LLMProvider
from recallfabric.services.ingest_service import default_ingest_job_store, process_ingest_job_sync


class MockExtractionProvider(LLMProvider):
    def __init__(self, name: str = "mock-ingest-llm", model: str = "mock-model") -> None:
        self.name = name
        self.model = model

    def chat(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.0,
        max_tokens: int | None = None,
        json_mode: bool = False,
    ) -> str:
        return json.dumps(
            {
                "memories": [
                    {
                        "content": "User lives in Seattle and works on cloud infrastructure",
                        "type": "fact",
                        "importance": 0.85,
                        "confidence": 0.95,
                        "creation_reason": "Directly stated in transcript",
                    },
                    {
                        "content": "User prefers concise answers",
                        "type": "preference",
                        "importance": 0.9,
                        "confidence": 0.9,
                        "creation_reason": "Expressed preference",
                    },
                ]
            }
        )

    def is_available(self) -> bool:
        return True


@pytest.fixture
def ingest_client():
    settings = Settings(
        app_name="RecallFabric",
        environment="development",
        auth_enabled=False,
    )
    app = create_app(settings)
    default_ingest_job_store.clear()
    with TestClient(app) as test_client:
        yield test_client


def test_ingest_transcript_creates_job(ingest_client, monkeypatch):
    """Test POST /v1/ingest queues an async job and returns 202 with status URL."""
    transcript = [
        {"role": "user", "content": "Hi, I live in Seattle and manage cloud systems."},
        {"role": "assistant", "content": "Hello! Good to know."},
        {"role": "user", "content": "Also please keep your answers concise."},
    ]

    payload = {
        "transcript": transcript,
        "source": "slack_integration",
        "user_id": "test_user_42",
    }

    resp = ingest_client.post("/v1/ingest", json=payload)
    assert resp.status_code == 202
    data = resp.json()
    assert "job_id" in data
    assert data["status"] == "pending"
    assert "status_url" in data
    assert f"/v1/ingest/jobs/{data['job_id']}" in data["status_url"]

    # Check job is in store
    job_id = data["job_id"]
    job_record = default_ingest_job_store.get_job(job_id)
    assert job_record is not None
    assert job_record["user_id"] == "test_user_42"
    assert job_record["message_count"] == 3


def test_get_ingest_job_status_flow(ingest_client):
    """Test polling GET /v1/ingest/jobs/{job_id} reflects progress and completion."""
    job_id = "test-job-uuid-123"
    default_ingest_job_store.create_job(job_id, "user_1", message_count=2)

    # Initial pending status
    resp = ingest_client.get(f"/v1/ingest/jobs/{job_id}")
    assert resp.status_code == 200
    assert resp.json()["status"] == "pending"

    # Simulate completion
    default_ingest_job_store.update_job(
        job_id,
        status="completed",
        extracted_count=2,
        memories=[
            {"id": "mem-1", "content": "Fact 1", "type": "fact", "importance": 0.8},
            {"id": "mem-2", "content": "Fact 2", "type": "fact", "importance": 0.9},
        ],
    )

    resp2 = ingest_client.get(f"/v1/ingest/jobs/{job_id}")
    assert resp2.status_code == 200
    completed_data = resp2.json()
    assert completed_data["status"] == "completed"
    assert completed_data["extracted_count"] == 2
    assert len(completed_data["memories"]) == 2


def test_get_ingest_job_not_found(ingest_client):
    """Test 404 response for nonexistent job ID."""
    resp = ingest_client.get("/v1/ingest/jobs/nonexistent-job-id")
    assert resp.status_code == 404
    assert "not found" in resp.json()["error"]["message"]


def test_ingest_processing_sync_logic(monkeypatch):
    """Test the ingest background task worker logic directly."""
    mock_provider = MockExtractionProvider()
    monkeypatch.setattr(
        "recallfabric.services.ingest_service.get_extraction_provider",
        lambda sett: mock_provider,
    )

    job_id = "job-worker-test"
    default_ingest_job_store.create_job(job_id, "user_test", message_count=2)

    process_ingest_job_sync(
        job_id=job_id,
        user_id="user_test",
        transcript=[
            {"role": "user", "content": "My favorite editor is Vim."},
            {"role": "assistant", "content": "Great choice."},
        ],
        source="unit_test",
        settings=Settings(environment="development", auth_enabled=False),
        engine=None,  # No DB connection in unit test, gracefully finishes
        embedder=None,
        job_store=default_ingest_job_store,
    )

    job = default_ingest_job_store.get_job(job_id)
    assert job["status"] == "completed"
    assert job["extracted_count"] == 2
    assert len(job["memories"]) == 2
