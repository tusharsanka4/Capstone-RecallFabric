"""HTTP checks against a migrated PostgreSQL schema, with real commits and locks."""

import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import event, select, text, update
from sqlalchemy.exc import OperationalError

from recallfabric.core.config import Settings
from recallfabric.db.connection import create_database_engine, get_database_engine
from recallfabric.db.models import Memory
from recallfabric.embeddings.service import (
    EmbeddingResult,
    EmbeddingUnavailable,
    LocalEmbeddingProvider,
    get_embedding_provider,
)
from recallfabric.main import create_app

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("RECALLFABRIC_RUN_DB_TESTS") != "1",
        reason="Set RECALLFABRIC_RUN_DB_TESTS=1 for PostgreSQL API tests",
    ),
]


class FakeEmbedder:
    model_id = "test"
    dimensions = 3

    def __init__(self):
        self.calls = []
        self.fail = False

    def embed(self, text, kind="passage"):
        self.calls.append((text, kind))
        if self.fail:
            raise EmbeddingUnavailable()
        return EmbeddingResult(model=self.model_id, dimensions=3, vector=[1, len(text), 0.5])


@pytest.fixture
def api():
    admin = create_database_engine(Settings())
    engine = create_database_engine(Settings())
    schema = "test_api_" + uuid4().hex
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
        app = create_app(Settings(_env_file=None))
        app.dependency_overrides[get_database_engine] = lambda: engine
        embedder = FakeEmbedder()
        app.dependency_overrides[get_embedding_provider] = lambda: embedder
        app.state.test_embedder = embedder
        with TestClient(app) as client:
            yield client, engine
    finally:
        engine.dispose()
        # Only the schema created above is removed; never the application's schema.
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def payload(**changes):
    return {
        "user_id": "alice",
        "content": "Learning Spring Boot",
        "type": "skill",
        "source": "conversation_1",
        "metadata": {"topic": "backend"},
        **changes,
    }


def replacement(version=1, **changes):
    values = payload()
    values.pop("user_id")
    return {**values, "expected_version": version, **changes}


def create(client, **changes):
    response = client.post("/memories", json=payload(**changes))
    assert response.status_code == 201, response.text
    return response


def test_create_get_update_history_and_delete(api):
    client, engine = api
    response = create(client)
    item = response.json()
    assert item["version"] == 1
    assert item["metadata"] == {"topic": "backend"}
    assert client.get(response.headers["Location"]).json() == item
    path = f"/memories/{item['id']}"
    params = {"user_id": "alice"}
    changed = client.put(
        path,
        params=params,
        json=replacement(content="Learning Django", source="conversation_2", status="disabled"),
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["version"] == 2
    assert changed.json()["previous_version"] == 1
    assert client.get(path, params=params).json()["status"] == "disabled"
    assert (
        client.post("/memories/search", json={"user_id": "alice", "query": "Django"}).json()[
            "items"
        ]
        == []
    )
    assert (
        len(
            client.post(
                "/memories/search",
                json={"user_id": "alice", "query": "Django", "status": "disabled"},
            ).json()["items"]
        )
        == 1
    )
    history = client.get(path + "/versions", params=params).json()["items"]
    assert [row["version"] for row in history] == [2, 1]
    assert history[1]["content"] == "Learning Spring Boot"
    assert history[1]["status"] == "superseded"
    assert client.put(path, params=params, json=replacement()).status_code == 409
    assert len(client.get(path + "/versions", params=params).json()["items"]) == 2
    deleted = client.delete(path, params=params)
    assert deleted.status_code == 204
    assert deleted.content == b""
    assert client.get(path, params=params).status_code == 404
    assert client.get(path + "/versions", params=params).status_code == 404
    assert client.delete(path, params=params).status_code == 404
    with engine.connect() as connection:
        assert connection.execute(select(Memory.id)).all() == []


def test_owner_scope_across_operations(api):
    client, _ = api
    item = create(client).json()
    path = f"/memories/{item['id']}"
    params = {"user_id": "bob"}
    assert client.get(path, params=params).status_code == 404
    assert client.get(path + "/versions", params=params).status_code == 404
    assert client.put(path, params=params, json=replacement()).status_code == 404
    assert client.delete(path, params=params).status_code == 404
    assert client.get("/memories", params=params).json()["items"] == []
    assert client.post("/memories/search", json={**params, "query": "Spring"}).json()["items"] == []
    assert client.get(path, params={"user_id": "alice"}).json()["version"] == 1


def test_list_pagination_filters_and_literal_search(api):
    client, _ = api
    create(client, content="Learn 100% Python", type="goal")
    create(client, content="Learn 1000 Python", type="goal")
    create(client, user_id="bob")
    first = client.get("/memories", params={"user_id": "alice", "limit": 1}).json()
    second = client.get("/memories", params={"user_id": "alice", "limit": 1, "offset": 1}).json()
    assert first["has_more"] is True
    assert second["has_more"] is False
    assert first["items"][0]["id"] != second["items"][0]["id"]
    assert (
        client.get("/memories", params={"user_id": "alice", "type": "skill"}).json()["items"] == []
    )
    found = client.post("/memories/search", json={"user_id": "alice", "query": "100%"}).json()
    assert [row["content"] for row in found["items"]] == ["Learn 100% Python"]
    assert (
        len(
            client.post(
                "/memories/search", json={"user_id": "alice", "query": "PYTHON", "type": "goal"}
            ).json()["items"]
        )
        == 2
    )


def test_changed_content_regenerates_embedding(api):
    client, engine = api
    item = create(client).json()
    with engine.begin() as connection:
        connection.execute(
            update(Memory).values(
                embedding=[1, 0, 0], embedding_model="test", embedding_dimensions=3
            )
        )
    path = f"/memories/{item['id']}"
    same = client.put(path, params={"user_id": "alice"}, json=replacement(importance=0.9))
    assert same.json()["embedding_model"] == "test"
    changed = client.put(
        path, params={"user_id": "alice"}, json=replacement(version=2, content="Different fact")
    )
    assert changed.status_code == 200
    assert changed.json()["embedding_model"] == "test"
    assert changed.json()["embedding_dimensions"] == 3
    assert len(client.app.state.test_embedder.calls) == 2
    with engine.connect() as connection:
        rows = connection.execute(
            select(Memory.version, Memory.embedding).order_by(Memory.version)
        ).all()
        assert rows[0].embedding is not None
        assert rows[1].embedding is not None
        assert rows[2].embedding is not None
        assert list(rows[2].embedding) != list(rows[1].embedding)


def test_embedding_failure_leaves_no_partial_write(api):
    client, engine = api
    embedder = client.app.state.test_embedder
    item = create(client).json()
    embedder.fail = True
    response = client.post("/memories", json=payload(content="Cannot embed"))
    assert response.status_code == 503
    assert response.json() == {"detail": "Embedding model unavailable"}
    response = client.put(
        f"/memories/{item['id']}",
        params={"user_id": "alice"},
        json=replacement(content="Cannot embed"),
    )
    assert response.status_code == 503
    with engine.connect() as connection:
        rows = connection.execute(select(Memory.version, Memory.status)).all()
        assert rows == [(1, "active")]


def test_model_change_reembeds_unchanged_content(api):
    client, _ = api
    item = create(client).json()
    client.app.state.test_embedder.model_id = "new-model"
    response = client.put(
        f"/memories/{item['id']}", params={"user_id": "alice"}, json=replacement()
    )
    assert response.status_code == 200
    assert response.json()["embedding_model"] == "new-model"
    assert len(client.app.state.test_embedder.calls) == 2


@pytest.mark.skipif(
    os.getenv("RECALLFABRIC_RUN_MODEL_TESTS") != "1", reason="Requires downloaded embedding model"
)
def test_real_local_embeddings_round_trip(api):
    client, engine = api
    provider = LocalEmbeddingProvider(Settings())
    client.app.dependency_overrides[get_embedding_provider] = lambda: provider
    response = create(client)
    assert response.json()["embedding_dimensions"] == provider.dimensions
    with engine.connect() as connection:
        vector = connection.execute(select(Memory.embedding)).scalar_one()
        assert len(vector) == provider.dimensions
    query = client.post("/embeddings", json={"text": "Which framework is the user learning?"})
    assert query.status_code == 200
    assert query.json()["model"] == response.json()["embedding_model"]
    assert len(query.json()["vector"]) == provider.dimensions


def test_concurrent_updates_have_one_winner(api):
    client, _ = api
    item = create(client).json()
    path = f"/memories/{item['id']}"

    def edit(content):
        return client.put(path, params={"user_id": "alice"}, json=replacement(content=content))

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(edit, ["First change", "Second change"]))
    assert sorted(response.status_code for response in results) == [200, 409]
    history = client.get(path + "/versions", params={"user_id": "alice"}).json()["items"]
    assert [row["version"] for row in history] == [2, 1]


def test_invalid_requests_and_missing_ids(api):
    client, _ = api
    assert client.post("/memories", json=payload(content=" ")).status_code == 422
    assert client.post("/memories", json=payload(confidence=2)).status_code == 422
    assert client.get("/memories").status_code == 422
    assert client.get("/memories", params={"user_id": " ", "limit": 101}).status_code == 422
    assert client.get("/memories/not-a-uuid", params={"user_id": "alice"}).status_code == 422
    assert client.get(f"/memories/{uuid4()}", params={"user_id": "alice"}).status_code == 404
    assert (
        client.post("/memories/search", json={"user_id": "alice", "query": " "}).status_code == 422
    )


def test_failed_update_rolls_back_previous_revision(api):
    client, engine = api
    item = create(client).json()
    with engine.begin() as connection:
        connection.execute(
            text(
                "ALTER TABLE memories ADD CONSTRAINT test_reject_content "
                "CHECK (content <> 'reject')"
            )
        )
    path = f"/memories/{item['id']}"
    response = client.put(path, params={"user_id": "alice"}, json=replacement(content="reject"))
    assert response.status_code == 409
    assert "test_reject_content" not in response.text
    current = client.get(path, params={"user_id": "alice"}).json()
    assert current["version"] == 1
    assert current["status"] == "active"
    assert len(client.get(path + "/versions", params={"user_id": "alice"}).json()["items"]) == 1


def test_database_errors_are_sanitized(api):
    client, engine = api

    def fail(*args):
        raise OperationalError("private SQL", {}, Exception("private credentials"))

    event.listen(engine, "before_cursor_execute", fail)
    try:
        response = client.get("/memories", params={"user_id": "alice"})
        assert response.status_code == 503
        assert response.json() == {"detail": "Database unavailable"}
        assert client.get("/health").status_code == 200
    finally:
        event.remove(engine, "before_cursor_execute", fail)
