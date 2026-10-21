import json
import os
from datetime import UTC, datetime
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from openai import APIConnectionError, APITimeoutError
from sqlalchemy import select, text

from recallfabric.api.extraction import get_llm_client
from recallfabric.core.config import Settings
from recallfabric.db.models import Memory
from recallfabric.db.session import get_session
from recallfabric.embeddings.service import EmbeddingResult, get_embedding_provider
from recallfabric.extraction.filters import filter_candidate
from recallfabric.main import create_app


class FakeEmbedder:
    model_id = "test"
    dimensions = 3

    def embed(self, text, kind="passage"):
        return EmbeddingResult(model=self.model_id, dimensions=3, vector=[1.0, 0.0, 0.0])


class MockLLMResponse:
    def __init__(self, content):
        self.choices = [MagicMock(message=MagicMock(content=content))]


def make_mock_client(content=None, side_effect=None):
    mock = MagicMock()
    if side_effect:
        mock.chat.completions.create.side_effect = side_effect
    else:
        mock.chat.completions.create.return_value = MockLLMResponse(content)
    return mock


def test_extraction_llm_unreachable():
    app = create_app(Settings(_env_file=None, environment="test"))
    req_mock = MagicMock()
    mock_client = make_mock_client(side_effect=APIConnectionError(request=req_mock))
    app.dependency_overrides[get_llm_client] = lambda: mock_client
    app.dependency_overrides[get_embedding_provider] = lambda: FakeEmbedder()
    app.dependency_overrides[get_session] = lambda: MagicMock()

    with TestClient(app) as client:
        response = client.post(
            "/extraction",
            json={
                "user_id": "alice",
                "text": "I live in Seattle",
                "source": "chat",
            },
        )
        assert response.status_code == 503
        assert "unreachable" in response.json()["detail"].lower()


def test_extraction_invalid_json():
    app = create_app(Settings(_env_file=None, environment="test"))
    mock_client = make_mock_client(content="invalid json {not a dict}")
    app.dependency_overrides[get_llm_client] = lambda: mock_client
    app.dependency_overrides[get_embedding_provider] = lambda: FakeEmbedder()
    app.dependency_overrides[get_session] = lambda: MagicMock()

    with TestClient(app) as client:
        response = client.post(
            "/extraction",
            json={
                "user_id": "alice",
                "text": "I live in Seattle",
                "source": "chat",
            },
        )
        assert response.status_code == 502
        assert "json" in response.json()["detail"].lower()


def test_extraction_filtered_garbage():
    garbage_payload = json.dumps(
        {
            "memories": [
                {
                    "content": "I am an AI assistant and I cannot remember things",
                    "importance": 0.9,
                    "confidence": 0.9,
                },
                {"content": "How are you doing today?", "importance": 0.9, "confidence": 0.9},
                {"content": "hello?", "importance": 0.9, "confidence": 0.9},
                {"content": "word", "importance": 0.9, "confidence": 0.9},
                {"content": "User likes tea", "importance": 0.4, "confidence": 0.9},
                {"content": "User likes coffee", "importance": 0.8, "confidence": 0.3},
            ]
        }
    )
    app = create_app(Settings(_env_file=None, environment="test"))
    mock_client = make_mock_client(content=garbage_payload)
    app.dependency_overrides[get_llm_client] = lambda: mock_client
    app.dependency_overrides[get_embedding_provider] = lambda: FakeEmbedder()
    mock_session = MagicMock()
    app.dependency_overrides[get_session] = lambda: mock_session

    with TestClient(app) as client:
        response = client.post(
            "/extraction",
            json={
                "user_id": "alice",
                "text": "Hello, how are you?",
                "source": "chat",
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["extracted"] == []
        mock_session.add.assert_not_called()


def test_extraction_multi_fact():
    facts_payload = json.dumps(
        {
            "memories": [
                {
                    "content": "User's name is Alice",
                    "type": "profile",
                    "importance": 0.95,
                    "confidence": 0.95,
                    "creation_reason": "name stated",
                },
                {
                    "content": "User works as a software engineer",
                    "type": "profile",
                    "importance": 0.9,
                    "confidence": 0.9,
                    "creation_reason": "job stated",
                },
                {
                    "content": "User likes Python",
                    "type": "preference",
                    "importance": 0.8,
                    "confidence": 0.85,
                    "creation_reason": "language preference",
                },
            ]
        }
    )
    app = create_app(Settings(_env_file=None, environment="test"))
    mock_client = make_mock_client(content=facts_payload)
    app.dependency_overrides[get_llm_client] = lambda: mock_client
    app.dependency_overrides[get_embedding_provider] = lambda: FakeEmbedder()

    mock_session = MagicMock()
    mock_session.begin.return_value.__enter__.return_value = None
    mock_session.begin.return_value.__exit__.return_value = None

    def populate_fields(mem):
        now = datetime.now(UTC)
        mem.id = uuid4()
        mem.version = 1
        mem.status = "active"
        mem.access_count = 0
        mem.created_at = now
        mem.updated_at = now

    mock_session.add.side_effect = populate_fields
    app.dependency_overrides[get_session] = lambda: mock_session

    with TestClient(app) as client:
        response = client.post(
            "/extraction",
            json={
                "user_id": "alice",
                "text": "My name is Alice, I work as a software engineer and like Python.",
                "source": "chat",
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert len(data["extracted"]) == 3
        contents = [m["content"] for m in data["extracted"]]
        assert "User's name is Alice" in contents
        assert "User works as a software engineer" in contents
        assert "User likes Python" in contents


def test_extraction_bad_input():
    app = create_app(Settings(_env_file=None, environment="test"))
    with TestClient(app) as client:
        r1 = client.post(
            "/extraction",
            json={"user_id": "", "text": "I like Python", "source": "chat"},
        )
        assert r1.status_code == 422

        r2 = client.post(
            "/extraction",
            json={"user_id": "alice", "text": "   ", "source": "chat"},
        )
        assert r2.status_code == 422


def test_extraction_rollback_unit():
    facts_payload = json.dumps(
        {
            "memories": [
                {
                    "content": "User lives in Seattle",
                    "type": "profile",
                    "importance": 0.9,
                    "confidence": 0.9,
                },
                {
                    "content": "User likes hiking",
                    "type": "preference",
                    "importance": 0.8,
                    "confidence": 0.8,
                },
            ]
        }
    )
    app = create_app(Settings(_env_file=None, environment="test"))
    mock_client = make_mock_client(content=facts_payload)
    app.dependency_overrides[get_llm_client] = lambda: mock_client
    app.dependency_overrides[get_embedding_provider] = lambda: FakeEmbedder()

    mock_session = MagicMock()
    mock_session.flush.side_effect = [None, RuntimeError("database flush failure")]
    mock_session.begin.return_value.__enter__.return_value = None
    mock_session.begin.return_value.__exit__.return_value = None
    app.dependency_overrides[get_session] = lambda: mock_session

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            "/extraction",
            json={
                "user_id": "alice",
                "text": "I live in Seattle and like hiking.",
                "source": "chat",
            },
        )
        assert response.status_code >= 400


@pytest.mark.skipif(
    os.getenv("RECALLFABRIC_RUN_DB_TESTS") != "1",
    reason="Set RECALLFABRIC_RUN_DB_TESTS=1 for PostgreSQL extraction tests",
)
def test_extraction_single_transaction_rollback(retrieval_api):
    client, engine, _ = retrieval_api

    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "ALTER TABLE memories ADD CONSTRAINT ck_test_reject "
                    "CHECK (content <> 'User rejects this')"
                )
            )

        facts_payload = json.dumps(
            {
                "memories": [
                    {
                        "content": "User lives in Portland",
                        "type": "profile",
                        "importance": 0.9,
                        "confidence": 0.9,
                    },
                    {
                        "content": "User rejects this",
                        "type": "fact",
                        "importance": 0.8,
                        "confidence": 0.8,
                    },
                ]
            }
        )
        mock_client = make_mock_client(content=facts_payload)
        client.app.dependency_overrides[get_llm_client] = lambda: mock_client

        response = client.post(
            "/extraction",
            json={
                "user_id": "rollback_user",
                "text": "User lives in Portland and reject.",
                "source": "chat",
            },
        )
        assert response.status_code in [409, 500]

        from sqlalchemy.orm import Session

        with Session(engine) as s:
            rows = s.scalars(select(Memory).where(Memory.user_id == "rollback_user")).all()
            assert len(rows) == 0
    finally:
        with engine.begin() as connection:
            connection.execute(
                text("ALTER TABLE memories DROP CONSTRAINT IF EXISTS ck_test_reject")
            )


@pytest.mark.skipif(
    os.getenv("RECALLFABRIC_RUN_DB_TESTS") != "1",
    reason="Set RECALLFABRIC_RUN_DB_TESTS=1 for PostgreSQL extraction tests",
)
def test_memory_extraction_pipeline_db(retrieval_api):
    client, engine, _ = retrieval_api

    facts_payload = json.dumps(
        {
            "memories": [
                {
                    "content": "User loves Python",
                    "type": "preference",
                    "importance": 0.9,
                    "confidence": 1.0,
                    "creation_reason": "explicit",
                }
            ]
        }
    )
    mock_client = make_mock_client(content=facts_payload)
    client.app.dependency_overrides[get_llm_client] = lambda: mock_client

    response = client.post(
        "/extraction",
        json={
            "user_id": "test_extract_user",
            "text": "I really love programming in Python.",
            "source": "conversation_123",
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert "extracted" in data
    memories = data["extracted"]
    assert len(memories) == 1
    assert memories[0]["content"] == "User loves Python"
    assert memories[0]["type"] == "preference"
    assert memories[0]["user_id"] == "test_extract_user"
    assert memories[0]["importance"] == 0.9
    assert memories[0]["source"] == "conversation_123"

    mem_id = memories[0]["id"]
    get_res = client.get(f"/memories/{mem_id}", params={"user_id": "test_extract_user"})
    assert get_res.status_code == 200
    assert get_res.json()["content"] == "User loves Python"


TABLE_CASES = [
    ("User likes spicy ramen", 0.85, 0.90, True, None),
    ("User's name is Alice", 0.95, 0.95, True, None),
    ("User lives in San Francisco", 0.90, 0.90, True, None),
    ("User works as a software engineer", 0.88, 0.92, True, None),
    ("User speaks fluent Spanish", 0.80, 0.85, True, None),
    ("User plays acoustic guitar", 0.75, 0.80, True, None),
    ("User has an allergy to peanuts", 0.90, 0.95, True, None),
    ("User graduated from MIT", 0.85, 0.90, True, None),
    ("User owns a Golden Retriever named Max", 0.80, 0.85, True, None),
    ("User's favorite programming language is Python", 0.85, 0.90, True, None),
    ("User prefers dark mode in editors", 0.70, 0.80, True, None),
    ("User wants to run a marathon", 0.80, 0.85, True, None),
    ("User is a vegetarian", 0.85, 0.90, True, None),
    ("User drives a Tesla Model 3", 0.80, 0.85, True, None),
    ("User drinks black coffee without sugar", 0.75, 0.80, True, None),
    ("User's sister is named Sarah", 0.80, 0.85, True, None),
    ("User is hungry right now", 0.80, 0.80, False, "temporary"),
    ("User is in a meeting", 0.80, 0.80, False, "temporary"),
    ("User is on a call at the moment", 0.80, 0.80, False, "temporary"),
    ("User is tired today", 0.80, 0.80, False, "temporary"),
    ("User is feeling sleepy", 0.80, 0.80, False, "temporary"),
    ("User is eating lunch", 0.80, 0.80, False, "temporary"),
    ("User is in traffic", 0.80, 0.80, False, "temporary"),
    ("User is busy tonight", 0.80, 0.80, False, "temporary"),
    ("I love programming in Python", 0.85, 0.90, False, "third person"),
    ("My name is John", 0.90, 0.90, False, "third person"),
    ("She lives in London", 0.85, 0.90, False, "third person"),
    ("User is asking what time it is?", 0.80, 0.80, False, "question"),
    ("Does User like pizza?", 0.80, 0.80, False, "question"),
    ("Hello there!", 0.80, 0.80, False, "greeting"),
    ("User says good morning", 0.80, 0.80, False, "conversational"),
    ("As an AI, I can help you with that", 0.80, 0.80, False, "assistant"),
    ("User: I don't know how to answer", 0.80, 0.80, False, "assistant"),
    ("User noticed a blue car", 0.40, 0.90, False, "threshold"),
    ("User might possibly like skiing", 0.80, 0.40, False, "threshold"),
    ("User", 0.90, 0.90, False, "too short"),
]


def test_filters_table_driven_36_cases():
    settings = Settings(_env_file=None, environment="test")
    assert len(TABLE_CASES) >= 30

    for content, importance, confidence, expected_valid, reason_keyword in TABLE_CASES:
        valid, reason = filter_candidate(content, importance, confidence, settings)
        assert valid == expected_valid, (
            f"Failed for {content!r}: expected {expected_valid}, got {valid} ({reason})"
        )
        if not expected_valid:
            assert reason is not None
            if reason_keyword:
                assert reason_keyword.lower() in reason.lower()


def test_extraction_endpoint_table_driven_integration():
    settings = Settings(_env_file=None, environment="test")
    app = create_app(settings)

    candidates = [
        {
            "content": content,
            "type": "fact",
            "importance": importance,
            "confidence": confidence,
            "creation_reason": "test",
        }
        for content, importance, confidence, _, _ in TABLE_CASES
    ]
    payload = json.dumps({"memories": candidates})
    mock_client = make_mock_client(content=payload)
    app.dependency_overrides[get_llm_client] = lambda: mock_client
    app.dependency_overrides[get_embedding_provider] = lambda: FakeEmbedder()
    mock_session = MagicMock()
    app.dependency_overrides[get_session] = lambda: mock_session

    with TestClient(app) as client:
        response = client.post(
            "/extraction",
            json={
                "user_id": "alice",
                "text": "Extensive text containing multiple statements.",
                "source": "test",
                "dry_run": True,
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["extracted"] == []
        assert len(data["candidates"]) == len(TABLE_CASES)
        expected_rejected_count = sum(1 for _, _, _, valid, _ in TABLE_CASES if not valid)
        assert len(data["rejected"]) == expected_rejected_count
        mock_session.add.assert_not_called()


def test_extraction_dry_run():
    app = create_app(Settings(_env_file=None, environment="test"))
    payload = json.dumps(
        {
            "memories": [
                {
                    "content": "User likes spicy ramen",
                    "type": "preference",
                    "importance": 0.85,
                    "confidence": 0.90,
                },
                {
                    "content": "User is hungry right now",
                    "type": "fact",
                    "importance": 0.80,
                    "confidence": 0.80,
                },
            ]
        }
    )
    mock_client = make_mock_client(content=payload)
    app.dependency_overrides[get_llm_client] = lambda: mock_client
    app.dependency_overrides[get_embedding_provider] = lambda: FakeEmbedder()
    mock_session = MagicMock()
    app.dependency_overrides[get_session] = lambda: mock_session

    with TestClient(app) as client:
        response = client.post(
            "/extraction",
            json={
                "user_id": "alice",
                "text": "I like spicy ramen and I am hungry right now.",
                "source": "chat",
                "dry_run": True,
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["extracted"] == []
        assert len(data["candidates"]) == 2
        assert len(data["rejected"]) == 1
        assert data["rejected"][0]["content"] == "User is hungry right now"
        assert "temporary" in data["rejected"][0]["reason"].lower()
        mock_session.add.assert_not_called()


def test_extraction_invalid_llm_outputs():
    app = create_app(Settings(_env_file=None, environment="test"))
    mock_session = MagicMock()
    app.dependency_overrides[get_session] = lambda: mock_session
    app.dependency_overrides[get_embedding_provider] = lambda: FakeEmbedder()

    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = APITimeoutError(request=MagicMock())
    app.dependency_overrides[get_llm_client] = lambda: mock_client
    with TestClient(app) as client:
        r_timeout = client.post(
            "/extraction",
            json={"user_id": "alice", "text": "test", "source": "chat"},
        )
        assert r_timeout.status_code == 504

    mock_client = make_mock_client(content="[1, 2, 3]")
    app.dependency_overrides[get_llm_client] = lambda: mock_client
    with TestClient(app) as client:
        r_nondict = client.post(
            "/extraction",
            json={"user_id": "alice", "text": "test", "source": "chat"},
        )
        assert r_nondict.status_code == 502

    mock_client = make_mock_client(content='{"something_else": []}')
    app.dependency_overrides[get_llm_client] = lambda: mock_client
    with TestClient(app) as client:
        r_missing = client.post(
            "/extraction",
            json={"user_id": "alice", "text": "test", "source": "chat"},
        )
        assert r_missing.status_code == 502

    mock_client = make_mock_client(content='{"memories": "not a list"}')
    app.dependency_overrides[get_llm_client] = lambda: mock_client
    with TestClient(app) as client:
        r_nonlist = client.post(
            "/extraction",
            json={"user_id": "alice", "text": "test", "source": "chat"},
        )
        assert r_nonlist.status_code == 502
