import json
import os
from pathlib import Path
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from openai import APIConnectionError
from pydantic import ValidationError
from sqlalchemy import event, select, text

from recallfabric.api.extraction import get_llm_client
from recallfabric.core.config import Settings
from recallfabric.db.connection import create_database_engine, get_database_engine
from recallfabric.db.models import Memory
from recallfabric.embeddings.service import EmbeddingResult, get_embedding_provider
from recallfabric.main import create_app
from recallfabric.schemas.memory import MemoryRead


class ConflictDeterministicEmbedder:
    model_id = "test-conflict-model"
    dimensions = 3

    def __init__(self, mapping=None):
        self.mapping = mapping or {}

    def embed(self, text, kind="passage"):
        cleaned = text.strip().lower()
        vec = self.mapping.get(cleaned, [0.0, 0.0, 1.0])
        return EmbeddingResult(model=self.model_id, dimensions=3, vector=vec)


def test_conflict_config_and_schemas():
    settings = Settings(_env_file=None)
    assert settings.conflict_min_similarity == 0.70

    custom = Settings(_env_file=None, conflict_min_similarity=0.65)
    assert custom.conflict_min_similarity == 0.65

    with pytest.raises(ValidationError):
        Settings(_env_file=None, conflict_min_similarity=1.5)

    with pytest.raises(ValidationError):
        Settings(_env_file=None, conflict_min_similarity=-0.1)

    read_model = MemoryRead.model_validate(
        {
            "id": uuid4(),
            "user_id": "alice",
            "content": "User is learning Django",
            "type": "skill",
            "source": "unit_test",
            "version": 2,
            "status": "active",
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:00:00Z",
            "access_count": 0,
            "action": "consolidated",
            "conflict_resolution": {
                "superseded_id": str(uuid4()),
                "previous_content": "User is learning Spring Boot",
                "reason": "Updated from: User is learning Spring Boot",
            },
        }
    )
    assert read_model.conflict_resolution is not None
    assert "superseded_id" in read_model.conflict_resolution


@pytest.fixture
def conflict_api():
    if os.getenv("RECALLFABRIC_RUN_DB_TESTS") != "1":
        pytest.skip("Set RECALLFABRIC_RUN_DB_TESTS=1 for PostgreSQL conflict tests")
    admin = create_database_engine(Settings())
    engine = create_database_engine(Settings())
    schema = "test_conflict_" + uuid4().hex
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))

    @event.listens_for(engine, "connect")
    def set_schema(dbapi_connection, record):
        dbapi_connection.autocommit = True
        with dbapi_connection.cursor() as cursor:
            cursor.execute(f'SET search_path TO "{schema}", public')
        dbapi_connection.autocommit = False

    try:
        with engine.begin() as connection:
            config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
            config.attributes.update(connection=connection, schema=schema)
            command.upgrade(config, "head")

        embedder = ConflictDeterministicEmbedder(
            mapping={
                "user is learning spring boot": [1.0, 0.0, 0.0],
                "user is learning django": [0.75, 0.66, 0.0],
                "user likes tea": [0.0, 1.0, 0.0],
                "user likes coffee": [0.0, 0.83, 0.55],
                "what is user learning?": [0.75, 0.66, 0.0],
                "what is the user learning?": [0.75, 0.66, 0.0],
            }
        )
        app = create_app(
            Settings(
                _env_file=None,
                conflict_min_similarity=0.70,
                dedupe_threshold=0.92,
                retrieval_min_similarity=0.40,
            )
        )
        app.dependency_overrides[get_database_engine] = lambda: engine
        app.dependency_overrides[get_embedding_provider] = lambda: embedder
        with TestClient(app) as client:
            yield client, engine, embedder, app
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))


def test_conflict_spring_boot_to_django_supersedes(conflict_api):
    client, engine, _, app = conflict_api
    mock_llm = MagicMock()
    app.dependency_overrides[get_llm_client] = lambda: mock_llm

    resp_1 = MagicMock()
    c1 = MagicMock()
    c1.message.content = json.dumps(
        {
            "memories": [
                {
                    "content": "User is learning Spring Boot",
                    "type": "skill",
                    "importance": 0.8,
                    "confidence": 0.9,
                    "creation_reason": "explicit",
                }
            ]
        }
    )
    resp_1.choices = [c1]
    mock_llm.chat.completions.create.return_value = resp_1

    r1 = client.post(
        "/extraction",
        json={
            "user_id": "alice",
            "text": "I am learning Spring Boot",
            "source": "chat_1",
        },
    )
    assert r1.status_code == 201
    extracted_1 = r1.json()["extracted"]
    assert len(extracted_1) == 1
    id_1 = extracted_1[0]["id"]
    assert extracted_1[0]["version"] == 1
    assert extracted_1[0]["action"] == "created"

    def side_effect(*args, **kwargs):
        messages = kwargs.get("messages", [])
        system_content = messages[0]["content"] if messages else ""
        if "updates or contradicts" in system_content:
            mock_resp = MagicMock()
            ch = MagicMock()
            ch.message.content = json.dumps(
                {
                    "classification": "update",
                    "reason": "User switched from Spring Boot to Django",
                }
            )
            mock_resp.choices = [ch]
            return mock_resp
        mock_resp = MagicMock()
        ch = MagicMock()
        ch.message.content = json.dumps(
            {
                "memories": [
                    {
                        "content": "User is learning Django",
                        "type": "skill",
                        "importance": 0.85,
                        "confidence": 0.95,
                        "creation_reason": "explicit",
                    }
                ]
            }
        )
        mock_resp.choices = [ch]
        return mock_resp

    mock_llm.chat.completions.create.side_effect = side_effect

    r2 = client.post(
        "/extraction",
        json={
            "user_id": "alice",
            "text": "I am learning Django now",
            "source": "chat_2",
        },
    )
    assert r2.status_code == 201
    extracted_2 = r2.json()["extracted"]
    assert len(extracted_2) == 1
    item_2 = extracted_2[0]
    assert item_2["id"] == id_1
    assert item_2["version"] == 2
    assert item_2["previous_version"] == 1
    assert item_2["status"] == "active"
    assert item_2["content"] == "User is learning Django"
    assert item_2["creation_reason"] == "Updated from: User is learning Spring Boot"
    assert item_2["action"] == "consolidated"
    assert item_2["matched_memory_id"] == id_1
    assert item_2["conflict_resolution"] is not None
    assert item_2["conflict_resolution"]["superseded_id"] == id_1
    assert item_2["conflict_resolution"]["previous_content"] == "User is learning Spring Boot"

    with engine.connect() as conn:
        all_revisions = conn.execute(
            select(Memory).where(Memory.user_id == "alice").order_by(Memory.version.asc())
        ).all()
        assert len(all_revisions) == 2
        assert all_revisions[0].status == "superseded"
        assert all_revisions[0].version == 1
        assert all_revisions[1].status == "active"
        assert all_revisions[1].version == 2


def test_conflict_tea_and_coffee_not_superseded(conflict_api):
    client, engine, _, app = conflict_api
    mock_llm = MagicMock()
    app.dependency_overrides[get_llm_client] = lambda: mock_llm

    resp_1 = MagicMock()
    c1 = MagicMock()
    c1.message.content = json.dumps(
        {
            "memories": [
                {
                    "content": "User likes tea",
                    "type": "preference",
                    "importance": 0.7,
                    "confidence": 0.8,
                    "creation_reason": "stated",
                }
            ]
        }
    )
    resp_1.choices = [c1]
    mock_llm.chat.completions.create.return_value = resp_1

    r1 = client.post(
        "/extraction",
        json={"user_id": "bob", "text": "I like tea", "source": "chat_1"},
    )
    assert r1.status_code == 201
    id_1 = r1.json()["extracted"][0]["id"]

    def side_effect(*args, **kwargs):
        messages = kwargs.get("messages", [])
        system_content = messages[0]["content"] if messages else ""
        if "updates or contradicts" in system_content:
            mock_resp = MagicMock()
            ch = MagicMock()
            ch.message.content = json.dumps(
                {
                    "classification": "unrelated",
                    "reason": "User can like both tea and coffee",
                }
            )
            mock_resp.choices = [ch]
            return mock_resp
        mock_resp = MagicMock()
        ch = MagicMock()
        ch.message.content = json.dumps(
            {
                "memories": [
                    {
                        "content": "User likes coffee",
                        "type": "preference",
                        "importance": 0.8,
                        "confidence": 0.85,
                        "creation_reason": "stated",
                    }
                ]
            }
        )
        mock_resp.choices = [ch]
        return mock_resp

    mock_llm.chat.completions.create.side_effect = side_effect

    r2 = client.post(
        "/extraction",
        json={"user_id": "bob", "text": "I like coffee", "source": "chat_2"},
    )
    assert r2.status_code == 201
    extracted_2 = r2.json()["extracted"]
    assert len(extracted_2) == 1
    item_2 = extracted_2[0]
    assert item_2["id"] != id_1
    assert item_2["version"] == 1
    assert item_2["action"] == "created"
    assert item_2["conflict_resolution"] is None

    with engine.connect() as conn:
        active = conn.execute(
            select(Memory).where(Memory.user_id == "bob", Memory.status == "active")
        ).all()
        assert len(active) == 2


def test_retrieval_never_returns_superseded_and_versions_preserved(conflict_api):
    client, engine, _, app = conflict_api
    mock_llm = MagicMock()
    app.dependency_overrides[get_llm_client] = lambda: mock_llm

    def step1_side_effect(*args, **kwargs):
        mock_resp = MagicMock()
        ch = MagicMock()
        ch.message.content = json.dumps(
            {
                "memories": [
                    {
                        "content": "User is learning Spring Boot",
                        "type": "skill",
                        "importance": 0.8,
                        "confidence": 0.9,
                        "creation_reason": "explicit",
                    }
                ]
            }
        )
        mock_resp.choices = [ch]
        return mock_resp

    mock_llm.chat.completions.create.side_effect = step1_side_effect

    r1 = client.post(
        "/extraction",
        json={"user_id": "carol", "text": "I learn Spring Boot", "source": "s1"},
    )
    mem_id = r1.json()["extracted"][0]["id"]

    def step2_side_effect(*args, **kwargs):
        messages = kwargs.get("messages", [])
        system_content = messages[0]["content"] if messages else ""
        if "updates or contradicts" in system_content:
            mock_resp = MagicMock()
            ch = MagicMock()
            ch.message.content = json.dumps(
                {
                    "classification": "update",
                    "reason": "learning django replaces learning spring boot",
                }
            )
            mock_resp.choices = [ch]
            return mock_resp
        mock_resp = MagicMock()
        ch = MagicMock()
        ch.message.content = json.dumps(
            {
                "memories": [
                    {
                        "content": "User is learning Django",
                        "type": "skill",
                        "importance": 0.9,
                        "confidence": 0.9,
                        "creation_reason": "explicit",
                    }
                ]
            }
        )
        mock_resp.choices = [ch]
        return mock_resp

    mock_llm.chat.completions.create.side_effect = step2_side_effect

    r2 = client.post(
        "/extraction",
        json={"user_id": "carol", "text": "I learn Django", "source": "s2"},
    )
    assert r2.status_code == 201

    retrieve_res = client.post(
        "/memories/retrieve",
        json={"user_id": "carol", "query": "What is the user learning?", "limit": 10},
    )
    assert retrieve_res.status_code == 200
    retrieved_items = retrieve_res.json()["items"]
    assert len(retrieved_items) == 1
    assert retrieved_items[0]["content"] == "User is learning Django"
    assert retrieved_items[0]["version"] == 2
    assert all("Spring Boot" not in item["content"] for item in retrieved_items)

    versions_res = client.get(f"/memories/{mem_id}/versions", params={"user_id": "carol"})
    assert versions_res.status_code == 200
    versions_items = versions_res.json()["items"]
    assert len(versions_items) == 2
    assert versions_items[0]["version"] == 2
    assert versions_items[0]["status"] == "active"
    assert versions_items[0]["content"] == "User is learning Django"
    assert versions_items[1]["version"] == 1
    assert versions_items[1]["status"] == "superseded"
    assert versions_items[1]["content"] == "User is learning Spring Boot"


def test_llm_unavailable_fallback_safely(conflict_api):
    client, engine, _, app = conflict_api
    mock_llm = MagicMock()
    app.dependency_overrides[get_llm_client] = lambda: mock_llm

    resp_1 = MagicMock()
    c1 = MagicMock()
    c1.message.content = json.dumps(
        {
            "memories": [
                {
                    "content": "User is learning Spring Boot",
                    "type": "skill",
                    "importance": 0.8,
                    "confidence": 0.9,
                    "creation_reason": "explicit",
                }
            ]
        }
    )
    resp_1.choices = [c1]
    mock_llm.chat.completions.create.return_value = resp_1

    r1 = client.post(
        "/extraction",
        json={"user_id": "dave", "text": "Learning Spring Boot", "source": "s1"},
    )
    assert r1.status_code == 201
    id_1 = r1.json()["extracted"][0]["id"]

    def side_effect(*args, **kwargs):
        messages = kwargs.get("messages", [])
        system_content = messages[0]["content"] if messages else ""
        if "updates or contradicts" in system_content:
            req_mock = MagicMock()
            raise APIConnectionError(request=req_mock)
        mock_resp = MagicMock()
        ch = MagicMock()
        ch.message.content = json.dumps(
            {
                "memories": [
                    {
                        "content": "User is learning Django",
                        "type": "skill",
                        "importance": 0.85,
                        "confidence": 0.9,
                        "creation_reason": "explicit",
                    }
                ]
            }
        )
        mock_resp.choices = [ch]
        return mock_resp

    mock_llm.chat.completions.create.side_effect = side_effect

    r2 = client.post(
        "/extraction",
        json={"user_id": "dave", "text": "Learning Django", "source": "s2"},
    )
    assert r2.status_code == 201
    extracted_2 = r2.json()["extracted"]
    assert len(extracted_2) == 1
    item_2 = extracted_2[0]
    assert item_2["action"] == "created"
    assert item_2["id"] != id_1
    assert item_2["metadata"].get("conflict_check") == "skipped"

    with engine.connect() as conn:
        active = conn.execute(
            select(Memory).where(Memory.user_id == "dave", Memory.status == "active")
        ).all()
        assert len(active) == 2


def test_acceptance_changing_information(conflict_api):
    client, engine, _, app = conflict_api
    mock_llm = MagicMock()
    app.dependency_overrides[get_llm_client] = lambda: mock_llm

    def step1_side_effect(*args, **kwargs):
        mock_resp = MagicMock()
        ch = MagicMock()
        ch.message.content = json.dumps(
            {
                "memories": [
                    {
                        "content": "User is learning Spring Boot",
                        "type": "skill",
                        "importance": 0.8,
                        "confidence": 0.9,
                        "creation_reason": "stated",
                    }
                ]
            }
        )
        mock_resp.choices = [ch]
        return mock_resp

    mock_llm.chat.completions.create.side_effect = step1_side_effect

    r1 = client.post(
        "/extraction",
        json={"user_id": "acceptance_user", "text": "I learn Spring Boot", "source": "chat1"},
    )
    assert r1.status_code == 201
    mem_id = r1.json()["extracted"][0]["id"]

    def step2_side_effect(*args, **kwargs):
        messages = kwargs.get("messages", [])
        system_content = messages[0]["content"] if messages else ""
        if "updates or contradicts" in system_content:
            mock_resp = MagicMock()
            ch = MagicMock()
            ch.message.content = json.dumps(
                {
                    "classification": "update",
                    "reason": "Django updates Spring Boot",
                }
            )
            mock_resp.choices = [ch]
            return mock_resp
        mock_resp = MagicMock()
        ch = MagicMock()
        ch.message.content = json.dumps(
            {
                "memories": [
                    {
                        "content": "User is learning Django",
                        "type": "skill",
                        "importance": 0.9,
                        "confidence": 0.95,
                        "creation_reason": "stated",
                    }
                ]
            }
        )
        mock_resp.choices = [ch]
        return mock_resp

    mock_llm.chat.completions.create.side_effect = step2_side_effect

    r2 = client.post(
        "/extraction",
        json={"user_id": "acceptance_user", "text": "I learn Django", "source": "chat2"},
    )
    assert r2.status_code == 201

    retrieved = client.post(
        "/memories/retrieve",
        json={"user_id": "acceptance_user", "query": "What is user learning?", "limit": 10},
    ).json()["items"]
    assert len(retrieved) == 1
    assert retrieved[0]["content"] == "User is learning Django"

    versions = client.get(
        f"/memories/{mem_id}/versions", params={"user_id": "acceptance_user"}
    ).json()["items"]
    assert len(versions) == 2
    contents = [v["content"] for v in versions]
    assert "User is learning Django" in contents
    assert "User is learning Spring Boot" in contents
