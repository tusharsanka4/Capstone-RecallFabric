import json
from uuid import uuid4

import httpx
import pytest

from recallfabric.dashboard_client import (
    DashboardClientError,
    chat_with_service,
    check_status,
    clear_all_memories,
    create_memory,
    delete_memory,
    disable_memory,
    enable_memory,
    extract_memories,
    fetch_memories,
    get_memory,
    get_memory_history,
    get_memory_provenance,
    preview_extraction,
    retrieve_memories,
    search_memories,
    update_memory,
)


def test_dashboard_client_success():
    mem_id = str(uuid4())

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.endswith("/health"):
            return httpx.Response(200, json={"status": "ok"})
        if url.endswith("/api/tags"):
            return httpx.Response(200, json={"models": []})
        if request.method == "GET" and f"/memories/{mem_id}/versions" in url:
            return httpx.Response(200, json={"items": [{"id": mem_id, "version": 1}]})
        if request.method == "GET" and f"/memories/{mem_id}/provenance" in url:
            return httpx.Response(200, json={"events": [{"event_type": "created"}]})
        if request.method == "GET" and f"/memories/{mem_id}" in url:
            return httpx.Response(200, json={"id": mem_id, "version": 1, "content": "fact 1"})
        if request.method == "POST" and f"/memories/{mem_id}/disable" in url:
            return httpx.Response(200, json={"id": mem_id, "status": "disabled", "version": 2})
        if request.method == "POST" and f"/memories/{mem_id}/enable" in url:
            return httpx.Response(200, json={"id": mem_id, "status": "active", "version": 3})
        if request.method == "PUT" and f"/memories/{mem_id}" in url:
            return httpx.Response(200, json={"id": mem_id, "version": 2, "content": "updated"})
        if request.method == "DELETE" and f"/memories/{mem_id}" in url:
            return httpx.Response(204)
        if request.method == "POST" and url.endswith("/memories/search"):
            return httpx.Response(200, json={"items": [{"id": mem_id, "content": "fact 1"}]})
        if request.method == "POST" and url.endswith("/memories/retrieve"):
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": mem_id,
                            "content": "fact 1",
                            "score": 0.9,
                            "score_breakdown": {
                                "relevance": 0.9,
                                "importance": 0.8,
                                "confidence": 0.9,
                                "recency": 1.0,
                                "frequency": 0.5,
                            },
                        }
                    ]
                },
            )
        if request.method == "POST" and url.endswith("/extraction"):
            body = json.loads(request.content)
            if body.get("dry_run"):
                return httpx.Response(
                    200,
                    json={
                        "candidates": [{"content": "fact 1"}],
                        "rejected": [],
                        "extracted": [],
                    },
                )
            return httpx.Response(201, json={"extracted": [{"id": mem_id, "content": "fact 1"}]})
        if request.method == "POST" and url.endswith("/chat"):
            return httpx.Response(
                200,
                json={
                    "reply": "Hello!",
                    "memories_used": [{"content": "fact 1"}],
                    "extracted": [],
                },
            )
        if request.method == "POST" and url.endswith("/memories"):
            return httpx.Response(201, json={"id": mem_id, "version": 1, "content": "created"})
        if request.method == "GET" and "/memories" in url:
            return httpx.Response(200, json={"items": [{"id": mem_id, "content": "fact 1"}]})
        return httpx.Response(404, text="Not found")

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport)

    mems = fetch_memories("http://test", "alice", client=client)
    assert len(mems) == 1
    assert mems[0]["id"] == mem_id

    created = create_memory("http://test", "alice", "new fact", client=client)
    assert created["id"] == mem_id

    single = get_memory("http://test", "alice", mem_id, client=client)
    assert single["id"] == mem_id

    updated = update_memory("http://test", "alice", mem_id, 1, "updated", client=client)
    assert updated["version"] == 2

    disabled = disable_memory("http://test", "alice", mem_id, client=client)
    assert disabled["status"] == "disabled"

    enabled = enable_memory("http://test", "alice", mem_id, client=client)
    assert enabled["status"] == "active"

    history = get_memory_history("http://test", "alice", mem_id, client=client)
    assert len(history) == 1

    prov = get_memory_provenance("http://test", "alice", mem_id, client=client)
    assert len(prov) == 1

    searched = search_memories("http://test", "alice", "fact", client=client)
    assert len(searched) == 1

    retrieved = retrieve_memories("http://test", "alice", "query", client=client)
    assert len(retrieved) == 1
    assert "score_breakdown" in retrieved[0]

    preview = preview_extraction("http://test", "alice", "text", client=client)
    assert len(preview["candidates"]) == 1

    extracted = extract_memories("http://test", "alice", "text", client=client)
    assert len(extracted) == 1

    reply, used, _ = chat_with_service("http://test", "alice", "hi", [], client=client)
    assert reply == "Hello!"
    assert len(used) == 1

    ok, count = clear_all_memories("http://test", "alice", client=client)
    assert ok is True
    assert count == 1

    api_ok, ollama_ok = check_status("http://test", "http://ollama", client=client)
    assert api_ok is True
    assert ollama_ok is True


def test_dashboard_client_404():
    transport = httpx.MockTransport(lambda req: httpx.Response(404, text="Memory not found"))
    client = httpx.Client(transport=transport)

    with pytest.raises(DashboardClientError) as exc_info:
        get_memory("http://test", "alice", str(uuid4()), client=client)
    assert exc_info.value.status_code == 404
    assert "Memory not found" in exc_info.value.detail

    with pytest.raises(DashboardClientError) as exc_info:
        delete_memory("http://test", "alice", str(uuid4()), client=client)
    assert exc_info.value.status_code == 404


def test_dashboard_client_409():
    transport = httpx.MockTransport(
        lambda req: httpx.Response(409, text="Memory version has changed")
    )
    client = httpx.Client(transport=transport)

    with pytest.raises(DashboardClientError) as exc_info:
        update_memory(
            api_url="http://test",
            user_id="alice",
            memory_id=str(uuid4()),
            expected_version=1,
            content="conflict content",
            client=client,
        )
    assert exc_info.value.status_code == 409
    assert "Memory version has changed" in exc_info.value.detail


def test_dashboard_client_503():
    transport = httpx.MockTransport(
        lambda req: httpx.Response(503, text="Embedding model unavailable")
    )
    client = httpx.Client(transport=transport)

    with pytest.raises(DashboardClientError) as exc_info:
        retrieve_memories("http://test", "alice", "coffee", client=client)
    assert exc_info.value.status_code == 503

    with pytest.raises(DashboardClientError) as exc_info:
        chat_with_service("http://test", "alice", "hello", [], client=client)
    assert exc_info.value.status_code == 503
