import pytest
from pydantic import ValidationError
from sqlalchemy import text

from recallfabric.schemas.memory import MemoryRetrieve


def test_memory_retrieve_schema_validation():
    with pytest.raises(ValidationError):
        MemoryRetrieve(user_id="", query="test")

    with pytest.raises(ValidationError):
        MemoryRetrieve(user_id="alice", query="")

    with pytest.raises(ValidationError):
        MemoryRetrieve(user_id="alice", query="test", limit=0)

    with pytest.raises(ValidationError):
        MemoryRetrieve(user_id="alice", query="test", limit=101)

    with pytest.raises(ValidationError):
        MemoryRetrieve(user_id="alice", query="test", min_score=2.0)

    valid = MemoryRetrieve(user_id="alice", query="test", min_score=0.5)
    assert valid.min_score == 0.5


def test_retrieval_semantic_ordering(retrieval_api):
    client, engine, _ = retrieval_api

    client.post(
        "/memories",
        json={
            "user_id": "alice",
            "content": "semantically distant",
            "type": "fact",
            "source": "test",
            "importance": 0.5,
            "confidence": 0.5,
        },
    )
    client.post(
        "/memories",
        json={
            "user_id": "alice",
            "content": "semantically close",
            "type": "fact",
            "source": "test",
            "importance": 0.5,
            "confidence": 0.5,
        },
    )

    response = client.post(
        "/memories/retrieve",
        json={"user_id": "alice", "query": "query close", "min_score": 0.0},
    )
    assert response.status_code == 200
    data = response.json()
    items = data["items"]
    assert len(items) == 2
    assert items[0]["content"] == "semantically close"
    assert items[1]["content"] == "semantically distant"
    assert items[0]["score"] > items[1]["score"]


def test_retrieval_user_isolation(retrieval_api):
    client, _, _ = retrieval_api

    client.post(
        "/memories",
        json={
            "user_id": "alice",
            "content": "semantically close",
            "type": "fact",
            "source": "test",
        },
    )

    response = client.post(
        "/memories/retrieve",
        json={"user_id": "bob", "query": "query close", "min_score": 0.0},
    )
    assert response.status_code == 200
    assert response.json()["items"] == []


def test_retrieval_status_and_type_filters(retrieval_api):
    client, _, _ = retrieval_api

    client.post(
        "/memories",
        json={
            "user_id": "alice",
            "content": "semantically close",
            "type": "skill",
            "source": "test",
        },
    )
    r2 = client.post(
        "/memories",
        json={
            "user_id": "alice",
            "content": "semantically distant",
            "type": "preference",
            "source": "test",
        },
    )
    mem_id = r2.json()["id"]
    client.put(
        f"/memories/{mem_id}",
        params={"user_id": "alice"},
        json={
            "content": "semantically distant",
            "type": "preference",
            "source": "test",
            "status": "disabled",
            "expected_version": 1,
        },
    )

    r_type = client.post(
        "/memories/retrieve",
        json={"user_id": "alice", "query": "query close", "type": "skill", "min_score": 0.0},
    )
    assert r_type.status_code == 200
    items = r_type.json()["items"]
    assert len(items) == 1
    assert items[0]["type"] == "skill"

    r_disabled = client.post(
        "/memories/retrieve",
        json={"user_id": "alice", "query": "query close", "status": "disabled", "min_score": 0.0},
    )
    assert r_disabled.status_code == 200
    assert len(r_disabled.json()["items"]) == 1
    assert r_disabled.json()["items"][0]["status"] == "disabled"


def test_retrieval_min_score_cutoff(retrieval_api):
    client, _, _ = retrieval_api

    client.post(
        "/memories",
        json={
            "user_id": "alice",
            "content": "orthogonal",
            "type": "fact",
            "source": "test",
            "importance": 0.5,
            "confidence": 0.5,
        },
    )

    response_high = client.post(
        "/memories/retrieve",
        json={"user_id": "alice", "query": "query close", "min_score": 0.5},
    )
    assert response_high.status_code == 200
    assert response_high.json()["items"] == []

    response_low = client.post(
        "/memories/retrieve",
        json={"user_id": "alice", "query": "query close", "min_score": -0.5},
    )
    assert response_low.status_code == 200
    assert len(response_low.json()["items"]) == 1


def test_retrieval_unrelated_query_returns_empty(retrieval_api):
    client, _, _ = retrieval_api

    client.post(
        "/memories",
        json={
            "user_id": "alice",
            "content": "semantically close",
            "type": "fact",
            "source": "test",
        },
    )

    response = client.post(
        "/memories/retrieve",
        json={"user_id": "alice", "query": "query unrelated"},
    )
    assert response.status_code == 200
    assert response.json()["items"] == []


def test_retrieval_model_and_dimension_filtering(retrieval_api):
    client, engine, _ = retrieval_api

    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO memories ("
                "id, version, user_id, content, type, importance, confidence, "
                "source, status, embedding, embedding_model, embedding_dimensions"
                ") VALUES ("
                "gen_random_uuid(), 1, 'alice', 'other model memory', 'fact', "
                "0.5, 1.0, 'test', 'active', '[1.0, 0.0, 0.0]'::vector, "
                "'different-model', 3)"
            )
        )

    response = client.post(
        "/memories/retrieve",
        json={"user_id": "alice", "query": "query close", "min_score": 0.0},
    )
    assert response.status_code == 200
    assert response.json()["items"] == []


def test_retrieval_has_more_pagination(retrieval_api):
    client, _, _ = retrieval_api

    for i in range(3):
        client.post(
            "/memories",
            json={
                "user_id": "alice",
                "content": f"semantically close {i}",
                "type": "fact",
                "source": "test",
            },
        )

    r_limit2 = client.post(
        "/memories/retrieve",
        json={"user_id": "alice", "query": "query close", "limit": 2, "min_score": 0.0},
    )
    assert r_limit2.status_code == 200
    data = r_limit2.json()
    assert len(data["items"]) == 2
    assert data["has_more"] is True

    r_limit5 = client.post(
        "/memories/retrieve",
        json={"user_id": "alice", "query": "query close", "limit": 5, "min_score": 0.0},
    )
    assert r_limit5.status_code == 200
    data5 = r_limit5.json()
    assert len(data5["items"]) == 3
    assert data5["has_more"] is False


def test_retrieval_ranking_signals_and_breakdown(retrieval_api):
    client, _, _ = retrieval_api

    client.post(
        "/memories",
        json={
            "user_id": "alice",
            "content": "semantically close",
            "type": "fact",
            "source": "test",
            "importance": 0.5,
            "confidence": 0.8,
        },
    )
    client.post(
        "/memories",
        json={
            "user_id": "alice",
            "content": "target memory",
            "type": "fact",
            "source": "test",
            "importance": 0.9,
            "confidence": 0.8,
        },
    )

    response = client.post(
        "/memories/retrieve",
        json={"user_id": "alice", "query": "query close", "min_score": 0.0},
    )
    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 2

    assert items[0]["content"] == "target memory"
    assert items[1]["content"] == "semantically close"

    for it in items:
        bd = it.get("score_breakdown")
        assert bd is not None
        assert "relevance" in bd
        assert "importance" in bd
        assert "confidence" in bd
        assert "recency" in bd
        assert "frequency" in bd


def test_retrieval_ranking_by_frequency(retrieval_api):
    client, engine, _ = retrieval_api

    r1 = client.post(
        "/memories",
        json={
            "user_id": "alice",
            "content": "target memory",
            "type": "fact",
            "source": "test",
            "importance": 0.5,
            "confidence": 0.8,
        },
    )
    client.post(
        "/memories",
        json={
            "user_id": "alice",
            "content": "semantically close",
            "type": "fact",
            "source": "test",
            "importance": 0.5,
            "confidence": 0.8,
        },
    )

    mem1_id = r1.json()["id"]
    with engine.begin() as conn:
        conn.execute(text(f"UPDATE memories SET access_count = 50 WHERE id = '{mem1_id}'"))

    response = client.post(
        "/memories/retrieve",
        json={"user_id": "alice", "query": "query close", "min_score": 0.0, "track_access": False},
    )
    assert response.status_code == 200
    items = response.json()["items"]
    assert items[0]["id"] == mem1_id
    assert items[0]["score_breakdown"]["frequency"] > items[1]["score_breakdown"]["frequency"]


def test_retrieval_access_tracking_increments(retrieval_api):
    client, _, _ = retrieval_api

    create_res = client.post(
        "/memories",
        json={
            "user_id": "alice",
            "content": "semantically close",
            "type": "fact",
            "source": "test",
        },
    )
    mem_id = create_res.json()["id"]

    r_init = client.get(f"/memories/{mem_id}", params={"user_id": "alice"})
    assert r_init.json()["access_count"] == 0
    assert r_init.json()["last_accessed_at"] is None

    ret_res = client.post(
        "/memories/retrieve",
        json={"user_id": "alice", "query": "query close", "track_access": True},
    )
    assert ret_res.status_code == 200
    items = ret_res.json()["items"]
    assert len(items) == 1
    assert items[0]["access_count"] == 1

    r_after = client.get(f"/memories/{mem_id}", params={"user_id": "alice"})
    assert r_after.json()["access_count"] == 1
    assert r_after.json()["last_accessed_at"] is not None


def test_retrieval_track_access_false_does_not_increment(retrieval_api):
    client, _, _ = retrieval_api

    create_res = client.post(
        "/memories",
        json={
            "user_id": "alice",
            "content": "semantically close",
            "type": "fact",
            "source": "test",
        },
    )
    mem_id = create_res.json()["id"]

    ret_res = client.post(
        "/memories/retrieve",
        json={"user_id": "alice", "query": "query close", "track_access": False},
    )
    assert ret_res.status_code == 200
    assert ret_res.json()["items"][0]["access_count"] == 0

    r_after = client.get(f"/memories/{mem_id}", params={"user_id": "alice"})
    assert r_after.json()["access_count"] == 0
    assert r_after.json()["last_accessed_at"] is None
