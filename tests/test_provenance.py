import os
from pathlib import Path
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import event, text

from recallfabric.api.extraction import get_llm_client
from recallfabric.core.config import Settings
from recallfabric.db.connection import create_database_engine, get_database_engine
from recallfabric.embeddings.service import EmbeddingResult, get_embedding_provider
from recallfabric.main import create_app
from recallfabric.schemas.provenance import (
    MemoryEventRead,
    MemoryProvenanceResponse,
    ProvenanceFeedPage,
)


class FakeProvenanceEmbedder:
    model_id = "test-provenance-model"
    dimensions = 3

    def embed(self, text, kind="passage"):
        return EmbeddingResult(
            model=self.model_id,
            dimensions=3,
            vector=[1.0, 0.0, 0.0],
        )


def test_provenance_settings_validation():
    settings = Settings(_env_file=None)
    assert settings.extraction_max_snippet_chars == 200

    custom = Settings(_env_file=None, extraction_max_snippet_chars=500)
    assert custom.extraction_max_snippet_chars == 500

    with pytest.raises(ValidationError):
        Settings(_env_file=None, extraction_max_snippet_chars=5)

    with pytest.raises(ValidationError):
        Settings(_env_file=None, extraction_max_snippet_chars=5000)


def test_provenance_schemas():
    event_id = uuid4()
    mem_id = uuid4()
    event_read = MemoryEventRead(
        id=event_id,
        memory_id=mem_id,
        memory_version=1,
        user_id="alice",
        event_type="created",
        reason="Initial fact",
        source="unit_test",
        actor="user",
        confidence=0.9,
        detail={"confidence": 0.9},
        created_at="2026-01-01T00:00:00Z",
    )
    assert event_read.event_type == "created"
    assert event_read.confidence == 0.9

    prov_resp = MemoryProvenanceResponse(
        events=[event_read],
        items=[event_read],
    )
    assert len(prov_resp.events) == 1
    assert len(prov_resp.items) == 1

    feed_page = ProvenanceFeedPage(
        items=[event_read],
        events=[event_read],
        limit=20,
        offset=0,
        has_more=False,
    )
    assert len(feed_page.items) == 1
    assert feed_page.has_more is False


@pytest.fixture
def prov_api():
    if os.getenv("RECALLFABRIC_RUN_DB_TESTS") != "1":
        pytest.skip("Set RECALLFABRIC_RUN_DB_TESTS=1 for PostgreSQL provenance tests")
    admin = create_database_engine(Settings())
    engine = create_database_engine(Settings())
    schema = "test_prov_" + uuid4().hex
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

        embedder = FakeProvenanceEmbedder()
        app = create_app()
        app.state.embedding_provider = embedder
        app.dependency_overrides[get_database_engine] = lambda: engine
        app.dependency_overrides[get_embedding_provider] = lambda: embedder

        with TestClient(app) as client:
            yield client, engine, schema
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def test_provenance_lifecycle_single_event_each(prov_api):
    client, engine, _ = prov_api
    user_id = "user_" + uuid4().hex

    create_resp = client.post(
        "/memories",
        json={
            "user_id": user_id,
            "content": "User prefers coffee with oat milk",
            "type": "preference",
            "source": "chat",
            "importance": 0.8,
            "confidence": 0.95,
            "creation_reason": "User said coffee with oat milk",
        },
    )
    assert create_resp.status_code == 201
    memory_id = create_resp.json()["id"]

    feed = client.get(f"/provenance?user_id={user_id}").json()
    assert len(feed["events"]) == 1
    assert feed["events"][0]["event_type"] == "created"
    assert feed["events"][0]["memory_version"] == 1
    assert feed["events"][0]["confidence"] == 0.95

    update_resp = client.put(
        f"/memories/{memory_id}?user_id={user_id}",
        json={
            "expected_version": 1,
            "content": "User prefers coffee with almond milk",
            "type": "preference",
            "importance": 0.85,
            "confidence": 0.98,
            "source": "chat",
            "creation_reason": "User updated coffee preference",
            "status": "active",
        },
    )
    assert update_resp.status_code == 200

    feed = client.get(f"/provenance?user_id={user_id}").json()
    assert len(feed["events"]) == 2
    assert feed["events"][1]["event_type"] == "superseded"
    assert feed["events"][1]["memory_version"] == 2

    disable_resp = client.put(
        f"/memories/{memory_id}?user_id={user_id}",
        json={
            "expected_version": 2,
            "content": "User prefers coffee with almond milk",
            "type": "preference",
            "importance": 0.85,
            "confidence": 0.98,
            "source": "settings",
            "creation_reason": "User disabled memory",
            "status": "disabled",
        },
    )
    assert disable_resp.status_code == 200

    feed = client.get(f"/provenance?user_id={user_id}").json()
    assert len(feed["events"]) == 3
    assert feed["events"][2]["event_type"] == "disabled"
    assert feed["events"][2]["memory_version"] == 3

    enable_resp = client.put(
        f"/memories/{memory_id}?user_id={user_id}",
        json={
            "expected_version": 3,
            "content": "User prefers coffee with almond milk",
            "type": "preference",
            "importance": 0.85,
            "confidence": 0.98,
            "source": "settings",
            "creation_reason": "User re-enabled memory",
            "status": "active",
        },
    )
    assert enable_resp.status_code == 200

    feed = client.get(f"/provenance?user_id={user_id}").json()
    assert len(feed["events"]) == 4
    assert feed["events"][3]["event_type"] == "enabled"
    assert feed["events"][3]["memory_version"] == 4

    ret_resp = client.post(
        "/memories/retrieve",
        json={
            "user_id": user_id,
            "query": "What does user drink?",
            "limit": 5,
            "track_access": True,
        },
    )
    assert ret_resp.status_code == 200
    assert len(ret_resp.json()["items"]) >= 1

    feed = client.get(f"/provenance?user_id={user_id}").json()
    assert len(feed["events"]) == 5
    access_event = feed["events"][4]
    assert access_event["event_type"] == "accessed"
    assert "coffee" not in str(access_event.get("detail", {}).get("content", ""))
    assert "content" not in access_event.get("detail", {})

    del_resp = client.delete(f"/memories/{memory_id}?user_id={user_id}")
    assert del_resp.status_code == 204

    feed = client.get(f"/provenance?user_id={user_id}").json()
    assert len(feed["events"]) == 6
    del_event = feed["events"][5]
    assert del_event["event_type"] == "deleted"
    assert del_event["detail"] == {}

    single_prov = client.get(f"/memories/{memory_id}/provenance?user_id={user_id}")
    assert single_prov.status_code == 200
    assert len(single_prov.json()["events"]) == 6


def test_provenance_events_survive_superseding(prov_api):
    client, _, _ = prov_api
    user_id = "user_" + uuid4().hex

    create_resp = client.post(
        "/memories",
        json={
            "user_id": user_id,
            "content": "User likes Python",
            "type": "preference",
            "source": "chat",
            "creation_reason": "User said they like Python",
        },
    )
    memory_id = create_resp.json()["id"]

    client.put(
        f"/memories/{memory_id}?user_id={user_id}",
        json={
            "expected_version": 1,
            "content": "User loves Python 3.12",
            "type": "preference",
            "source": "chat",
            "creation_reason": "User specified version",
            "status": "active",
        },
    )

    prov_resp = client.get(f"/memories/{memory_id}/provenance?user_id={user_id}")
    assert prov_resp.status_code == 200
    events = prov_resp.json()["events"]
    assert len(events) == 2
    assert events[0]["event_type"] == "created"
    assert events[0]["memory_version"] == 1
    assert events[1]["event_type"] == "superseded"
    assert events[1]["memory_version"] == 2

    hist_resp = client.get(f"/memories/{memory_id}/versions?user_id={user_id}")
    assert hist_resp.status_code == 200
    assert len(hist_resp.json()["items"]) == 2


def test_provenance_user_isolation(prov_api):
    client, _, _ = prov_api
    alice = "alice_" + uuid4().hex
    bob = "bob_" + uuid4().hex

    create_resp = client.post(
        "/memories",
        json={
            "user_id": alice,
            "content": "Alice secret memory",
            "type": "fact",
            "source": "secret",
        },
    )
    alice_mem_id = create_resp.json()["id"]

    bob_feed = client.get(f"/provenance?user_id={bob}")
    assert bob_feed.status_code == 200
    assert len(bob_feed.json()["events"]) == 0

    bob_prov = client.get(f"/memories/{alice_mem_id}/provenance?user_id={bob}")
    assert bob_prov.status_code == 404


def test_provenance_delete_leaves_tombstone(prov_api):
    client, _, _ = prov_api
    user_id = "user_" + uuid4().hex

    create_resp = client.post(
        "/memories",
        json={
            "user_id": user_id,
            "content": "Temporary scratchpad fact",
            "type": "fact",
            "source": "scratchpad",
        },
    )
    mem_id = create_resp.json()["id"]

    del_resp = client.delete(f"/memories/{mem_id}?user_id={user_id}")
    assert del_resp.status_code == 204

    get_mem = client.get(f"/memories/{mem_id}?user_id={user_id}")
    assert get_mem.status_code == 404

    prov_resp = client.get(f"/memories/{mem_id}/provenance?user_id={user_id}")
    assert prov_resp.status_code == 200
    events = prov_resp.json()["events"]
    assert len(events) == 2
    assert events[0]["event_type"] == "created"
    assert events[1]["event_type"] == "deleted"
    assert events[1]["detail"] == {}

    alt_prov = client.get(f"/provenance/{mem_id}?user_id={user_id}")
    assert alt_prov.status_code == 200
    assert len(alt_prov.json()["events"]) == 2


def test_provenance_acceptance_three_event_history(prov_api):
    client, _, _ = prov_api
    user_id = "user_" + uuid4().hex

    c_resp = client.post(
        "/memories",
        json={
            "user_id": user_id,
            "content": "User works from home on Fridays",
            "type": "profile",
            "source": "chat",
            "creation_reason": "Friday WFH stated",
            "importance": 0.7,
            "confidence": 0.9,
        },
    )
    mem_id = c_resp.json()["id"]

    u_resp = client.put(
        f"/memories/{mem_id}?user_id={user_id}",
        json={
            "expected_version": 1,
            "content": "User works from home on Thursdays and Fridays",
            "type": "profile",
            "source": "chat",
            "creation_reason": "Updated schedule",
            "importance": 0.75,
            "confidence": 0.95,
            "status": "active",
        },
    )
    assert u_resp.status_code == 200

    d_resp = client.put(
        f"/memories/{mem_id}?user_id={user_id}",
        json={
            "expected_version": 2,
            "content": "User works from home on Thursdays and Fridays",
            "type": "profile",
            "source": "manual",
            "creation_reason": "Schedule paused",
            "importance": 0.75,
            "confidence": 0.95,
            "status": "disabled",
        },
    )
    assert d_resp.status_code == 200

    mem_prov = client.get(f"/memories/{mem_id}/provenance?user_id={user_id}")
    assert mem_prov.status_code == 200
    events = mem_prov.json()["events"]
    assert len(events) == 3
    assert [e["event_type"] for e in events] == ["created", "superseded", "disabled"]
    assert events[0]["source"] == "chat"
    assert events[0]["creation_reason"] == "Friday WFH stated"
    assert events[0]["confidence"] == 0.9
    assert events[1]["creation_reason"] == "Updated schedule"
    assert events[1]["confidence"] == 0.95

    feed_prov = client.get(f"/provenance?user_id={user_id}&memory_id={mem_id}")
    assert feed_prov.status_code == 200
    feed_events = feed_prov.json()["events"]
    assert len(feed_events) == 3
    assert [e["event_type"] for e in feed_events] == ["created", "superseded", "disabled"]


def test_extraction_stores_originating_snippet(prov_api):
    client, _, _ = prov_api
    user_id = "user_" + uuid4().hex

    mock_llm = MagicMock()
    mock_choice = MagicMock()
    mock_choice.message.content = (
        '{"memories": [{"content": "User prefers dark mode", "type": "preference", '
        '"importance": 0.8, "confidence": 0.95, "creation_reason": "User explicit preference"}]}'
    )
    mock_llm.chat.completions.create.return_value = MagicMock(choices=[mock_choice])
    client.app.dependency_overrides[get_llm_client] = lambda: mock_llm

    long_text = "I always prefer dark mode when working at night on my computer."
    resp = client.post(
        "/extraction",
        json={
            "user_id": user_id,
            "text": long_text,
            "source": "dialogue_turn_42",
            "deduplicate": False,
        },
    )
    assert resp.status_code == 201
    extracted = resp.json()["extracted"]
    assert len(extracted) == 1
    meta = extracted[0]["metadata"]
    assert meta["source_id"] == "dialogue_turn_42"
    assert "source_reference" in meta
    assert meta["source_reference"]["source_id"] == "dialogue_turn_42"
    assert meta["source_reference"]["snippet"] == long_text[:200]
    assert len(meta["snippet"]) <= 200

    feed = client.get(f"/provenance?user_id={user_id}").json()
    assert len(feed["events"]) == 1
    assert feed["events"][0]["event_type"] == "created"
