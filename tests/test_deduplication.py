import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import event, select, text

from recallfabric.api.extraction import get_llm_client
from recallfabric.core.config import Settings
from recallfabric.db.connection import create_database_engine, get_database_engine
from recallfabric.db.models import Memory
from recallfabric.embeddings.service import EmbeddingResult, get_embedding_provider
from recallfabric.main import create_app
from recallfabric.schemas.memory import MemoryCreate, MemoryRead


class DedupeDeterministicEmbedder:
    model_id = "test-dedupe-model"
    dimensions = 3

    def __init__(self, mapping=None):
        self.mapping = mapping or {}

    def embed(self, text, kind="passage"):
        cleaned = text.strip().lower()
        vec = self.mapping.get(cleaned, [0.0, 0.0, 1.0])
        return EmbeddingResult(model=self.model_id, dimensions=3, vector=vec)


def test_dedupe_schema_defaults():
    create_model = MemoryCreate(
        user_id="alice",
        content="Testing ramen",
        type="preference",
        source="unit_test",
    )
    assert create_model.deduplicate is False

    read_model = MemoryRead.model_validate(
        {
            "id": uuid4(),
            "user_id": "alice",
            "content": "Testing ramen",
            "type": "preference",
            "source": "unit_test",
            "version": 1,
            "status": "active",
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:00:00Z",
            "access_count": 0,
            "action": "consolidated",
            "matched_memory_id": uuid4(),
        }
    )
    assert read_model.action == "consolidated"
    assert read_model.matched_memory_id is not None


def test_dedupe_threshold_config():
    settings = Settings(_env_file=None)
    assert settings.dedupe_threshold == 0.92

    custom = Settings(_env_file=None, dedupe_threshold=0.85)
    assert custom.dedupe_threshold == 0.85

    with pytest.raises(ValidationError):
        Settings(_env_file=None, dedupe_threshold=1.5)

    with pytest.raises(ValidationError):
        Settings(_env_file=None, dedupe_threshold=-0.1)


@pytest.fixture
def dedupe_api():
    if os.getenv("RECALLFABRIC_RUN_DB_TESTS") != "1":
        pytest.skip("Set RECALLFABRIC_RUN_DB_TESTS=1 for PostgreSQL deduplication tests")
    admin = create_database_engine(Settings())
    engine = create_database_engine(Settings())
    schema = "test_dedupe_" + uuid4().hex
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

        embedder = DedupeDeterministicEmbedder(
            mapping={
                "i like spicy ramen": [1.0, 0.0, 0.0],
                "i really enjoy spicy ramen": [0.96, 0.28, 0.0],
                "i enjoy playing tennis": [0.0, 1.0, 0.0],
                "user likes spicy ramen": [1.0, 0.0, 0.0],
                "user really enjoys spicy ramen": [0.96, 0.28, 0.0],
                "user enjoys playing tennis": [0.0, 1.0, 0.0],
            }
        )
        app = create_app(Settings(_env_file=None, dedupe_threshold=0.92))
        app.dependency_overrides[get_database_engine] = lambda: engine
        app.dependency_overrides[get_embedding_provider] = lambda: embedder
        with TestClient(app) as client:
            yield client, engine, embedder, app
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))


def test_similar_phrasing_is_consolidated(dedupe_api):
    client, engine, _, _ = dedupe_api
    r1 = client.post(
        "/memories?deduplicate=true",
        json={
            "user_id": "alice",
            "content": "I like spicy ramen",
            "type": "preference",
            "source": "source_1",
            "importance": 0.6,
            "confidence": 0.7,
            "metadata": {"topic": "food"},
        },
    )
    assert r1.status_code == 201
    d1 = r1.json()
    assert d1["action"] == "created"
    first_id = d1["id"]

    r2 = client.post(
        "/memories?deduplicate=true",
        json={
            "user_id": "alice",
            "content": "I really enjoy spicy ramen",
            "type": "preference",
            "source": "source_2",
            "importance": 0.85,
            "confidence": 0.65,
            "metadata": {"sentiment": "positive"},
        },
    )
    assert r2.status_code == 200
    d2 = r2.json()
    assert d2["action"] == "consolidated"
    assert d2["matched_memory_id"] == first_id
    assert d2["id"] == first_id
    assert d2["version"] == 2
    assert d2["importance"] == 0.85
    assert d2["confidence"] == 0.7
    assert d2["metadata"]["topic"] == "food"
    assert d2["metadata"]["sentiment"] == "positive"
    assert d2["metadata"]["sources"] == ["source_1", "source_2"]

    with engine.connect() as conn:
        rows = conn.execute(
            select(Memory).where(Memory.user_id == "alice").order_by(Memory.version.asc())
        ).all()
        assert len(rows) == 2
        assert rows[0].status == "superseded"
        assert rows[1].status == "active"


def test_identical_content_is_ignored(dedupe_api):
    client, engine, _, _ = dedupe_api
    r1 = client.post(
        "/memories?deduplicate=true",
        json={
            "user_id": "alice",
            "content": "I like spicy ramen",
            "type": "preference",
            "source": "source_1",
            "importance": 0.5,
            "confidence": 0.5,
        },
    )
    assert r1.status_code == 201
    d1 = r1.json()

    r2 = client.post(
        "/memories?deduplicate=true",
        json={
            "user_id": "alice",
            "content": "  I LIKE SPICY RAMEN  ",
            "type": "preference",
            "source": "source_2",
            "importance": 0.9,
            "confidence": 0.8,
        },
    )
    assert r2.status_code == 200
    d2 = r2.json()
    assert d2["action"] == "ignored"
    assert d2["matched_memory_id"] == d1["id"]
    assert d2["version"] == 1
    assert d2["access_count"] == 1
    assert d2["importance"] == 0.9
    assert d2["confidence"] == 0.8
    assert d2["metadata"]["sources"] == ["source_1", "source_2"]

    with engine.connect() as conn:
        rows = conn.execute(select(Memory).where(Memory.user_id == "alice")).all()
        assert len(rows) == 1
        assert rows[0].version == 1
        assert rows[0].status == "active"


def test_different_facts_not_consolidated(dedupe_api):
    client, engine, _, _ = dedupe_api
    r1 = client.post(
        "/memories?deduplicate=true",
        json={
            "user_id": "alice",
            "content": "I like spicy ramen",
            "type": "preference",
            "source": "source_1",
        },
    )
    assert r1.status_code == 201

    r2 = client.post(
        "/memories?deduplicate=true",
        json={
            "user_id": "alice",
            "content": "I enjoy playing tennis",
            "type": "preference",
            "source": "source_2",
        },
    )
    assert r2.status_code == 201
    d2 = r2.json()
    assert d2["action"] == "created"
    assert d2["matched_memory_id"] is None
    assert d2["id"] != r1.json()["id"]

    with engine.connect() as conn:
        active = conn.execute(
            select(Memory).where(Memory.user_id == "alice", Memory.status == "active")
        ).all()
        assert len(active) == 2


def test_different_users_never_match(dedupe_api):
    client, engine, _, _ = dedupe_api
    r1 = client.post(
        "/memories?deduplicate=true",
        json={
            "user_id": "alice",
            "content": "I like spicy ramen",
            "type": "preference",
            "source": "source_1",
        },
    )
    assert r1.status_code == 201

    r2 = client.post(
        "/memories?deduplicate=true",
        json={
            "user_id": "bob",
            "content": "I really enjoy spicy ramen",
            "type": "preference",
            "source": "source_2",
        },
    )
    assert r2.status_code == 201
    d2 = r2.json()
    assert d2["action"] == "created"
    assert d2["matched_memory_id"] is None
    assert d2["user_id"] == "bob"

    with engine.connect() as conn:
        alice_memories = conn.execute(
            select(Memory).where(Memory.user_id == "alice", Memory.status == "active")
        ).all()
        bob_memories = conn.execute(
            select(Memory).where(Memory.user_id == "bob", Memory.status == "active")
        ).all()
        assert len(alice_memories) == 1
        assert len(bob_memories) == 1


def test_different_types_never_match(dedupe_api):
    client, engine, _, _ = dedupe_api
    r1 = client.post(
        "/memories?deduplicate=true",
        json={
            "user_id": "alice",
            "content": "I like spicy ramen",
            "type": "preference",
            "source": "source_1",
        },
    )
    assert r1.status_code == 201

    r2 = client.post(
        "/memories?deduplicate=true",
        json={
            "user_id": "alice",
            "content": "I really enjoy spicy ramen",
            "type": "goal",
            "source": "source_2",
        },
    )
    assert r2.status_code == 201
    d2 = r2.json()
    assert d2["action"] == "created"
    assert d2["matched_memory_id"] is None

    with engine.connect() as conn:
        active = conn.execute(
            select(Memory).where(Memory.user_id == "alice", Memory.status == "active")
        ).all()
        assert len(active) == 2


def test_threshold_is_configurable(dedupe_api):
    client, engine, embedder, _ = dedupe_api

    app_strict = create_app(Settings(_env_file=None, dedupe_threshold=0.98))
    app_strict.dependency_overrides[get_database_engine] = lambda: engine
    app_strict.dependency_overrides[get_embedding_provider] = lambda: embedder

    with TestClient(app_strict) as client_strict:
        r1 = client_strict.post(
            "/memories?deduplicate=true",
            json={
                "user_id": "dave",
                "content": "I like spicy ramen",
                "type": "preference",
                "source": "source_1",
            },
        )
        assert r1.status_code == 201

        r2 = client_strict.post(
            "/memories?deduplicate=true",
            json={
                "user_id": "dave",
                "content": "I really enjoy spicy ramen",
                "type": "preference",
                "source": "source_2",
            },
        )
        assert r2.status_code == 201
        assert r2.json()["action"] == "created"

    app_lenient = create_app(Settings(_env_file=None, dedupe_threshold=0.90))
    app_lenient.dependency_overrides[get_database_engine] = lambda: engine
    app_lenient.dependency_overrides[get_embedding_provider] = lambda: embedder

    with TestClient(app_lenient) as client_lenient:
        r3 = client_lenient.post(
            "/memories?deduplicate=true",
            json={
                "user_id": "eve",
                "content": "I like spicy ramen",
                "type": "preference",
                "source": "source_1",
            },
        )
        assert r3.status_code == 201

        r4 = client_lenient.post(
            "/memories?deduplicate=true",
            json={
                "user_id": "eve",
                "content": "I really enjoy spicy ramen",
                "type": "preference",
                "source": "source_2",
            },
        )
        assert r4.status_code == 200
        assert r4.json()["action"] == "consolidated"


def test_manual_post_default_keeps_existing_behavior(dedupe_api):
    client, engine, _, _ = dedupe_api
    r1 = client.post(
        "/memories",
        json={
            "user_id": "alice",
            "content": "I like spicy ramen",
            "type": "preference",
            "source": "source_1",
        },
    )
    assert r1.status_code == 201
    assert r1.json()["action"] is None

    r2 = client.post(
        "/memories",
        json={
            "user_id": "alice",
            "content": "I like spicy ramen",
            "type": "preference",
            "source": "source_2",
        },
    )
    assert r2.status_code == 201
    assert r2.json()["action"] is None
    assert r1.json()["id"] != r2.json()["id"]

    with engine.connect() as conn:
        active = conn.execute(
            select(Memory).where(Memory.user_id == "alice", Memory.status == "active")
        ).all()
        assert len(active) == 2


def test_extraction_endpoint_deduplication(dedupe_api):
    client, engine, _, app = dedupe_api
    mock_llm = MagicMock()
    app.dependency_overrides[get_llm_client] = lambda: mock_llm

    resp_mock_1 = MagicMock()
    choice_mock_1 = MagicMock()
    choice_mock_1.message.content = json.dumps(
        {
            "memories": [
                {
                    "content": "User likes spicy ramen",
                    "type": "preference",
                    "importance": 0.8,
                    "confidence": 0.8,
                    "creation_reason": "explicit",
                }
            ]
        }
    )
    resp_mock_1.choices = [choice_mock_1]
    mock_llm.chat.completions.create.return_value = resp_mock_1

    r1 = client.post(
        "/extraction",
        json={
            "user_id": "carol",
            "text": "I like spicy ramen",
            "source": "chat_1",
        },
    )
    assert r1.status_code == 201
    assert len(r1.json()["extracted"]) == 1
    assert r1.json()["extracted"][0]["action"] == "created"
    first_id = r1.json()["extracted"][0]["id"]

    resp_mock_2 = MagicMock()
    choice_mock_2 = MagicMock()
    choice_mock_2.message.content = json.dumps(
        {
            "memories": [
                {
                    "content": "User really enjoys spicy ramen",
                    "type": "preference",
                    "importance": 0.9,
                    "confidence": 0.85,
                    "creation_reason": "explicit",
                }
            ]
        }
    )
    resp_mock_2.choices = [choice_mock_2]
    mock_llm.chat.completions.create.return_value = resp_mock_2

    r2 = client.post(
        "/extraction",
        json={
            "user_id": "carol",
            "text": "I really enjoy spicy ramen",
            "source": "chat_2",
        },
    )
    assert r2.status_code == 201
    extracted2 = r2.json()["extracted"]
    assert len(extracted2) == 1
    assert extracted2[0]["action"] == "consolidated"
    assert extracted2[0]["matched_memory_id"] == first_id
    assert extracted2[0]["version"] == 2


def test_concurrency_identical_extractions(dedupe_api):
    _, engine, embedder, app = dedupe_api

    def run_create():
        c = TestClient(app)
        return c.post(
            "/memories?deduplicate=true",
            json={
                "user_id": "alice_concurrent",
                "content": "I like spicy ramen",
                "type": "preference",
                "source": "concurrency_test",
                "importance": 0.8,
                "confidence": 0.9,
            },
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        f1 = executor.submit(run_create)
        f2 = executor.submit(run_create)
        r1 = f1.result()
        r2 = f2.result()

    assert r1.status_code in (200, 201)
    assert r2.status_code in (200, 201)

    with engine.connect() as conn:
        active = conn.execute(
            select(Memory).where(
                Memory.user_id == "alice_concurrent",
                Memory.status == "active",
            )
        ).all()
        assert len(active) == 1


def test_acceptance_spicy_ramen(dedupe_api):
    client, engine, _, _ = dedupe_api
    r1 = client.post(
        "/memories?deduplicate=true",
        json={
            "user_id": "acceptance_user",
            "content": "I like spicy ramen",
            "type": "preference",
            "source": "chat_1",
            "importance": 0.7,
            "confidence": 0.8,
        },
    )
    assert r1.status_code == 201
    data1 = r1.json()
    assert data1["action"] == "created"

    r2 = client.post(
        "/memories?deduplicate=true",
        json={
            "user_id": "acceptance_user",
            "content": "I really enjoy spicy ramen",
            "type": "preference",
            "source": "chat_2",
            "importance": 0.9,
            "confidence": 0.85,
        },
    )
    assert r2.status_code == 200
    data2 = r2.json()
    assert data2["action"] == "consolidated"
    assert data2["matched_memory_id"] == data1["id"]
    assert data2["id"] == data1["id"]
    assert data2["version"] == 2
    assert data2["importance"] == 0.9
    assert data2["confidence"] == 0.85
    assert "chat_1" in data2["metadata"]["sources"]
    assert "chat_2" in data2["metadata"]["sources"]

    with engine.connect() as conn:
        active = conn.execute(
            select(Memory).where(Memory.user_id == "acceptance_user", Memory.status == "active")
        ).all()
        assert len(active) == 1
        assert active[0].version == 2
