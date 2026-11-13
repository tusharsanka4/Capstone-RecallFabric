"""Tests for Module C4: Python Client SDK (RecallFabric & AsyncRecallFabric).

Covers:
- Unit tests with mocked httpx transports (success, retries, auth error, timeout).
- `with_memory` and `async_with_memory` wrappers.
- Framework adapters (LangChain and LlamaIndex).
- Full integration test against FastAPI app instance.
"""

from __future__ import annotations

import json
from uuid import uuid4

import httpx
import pytest
from recallfabric_client import (
    AsyncRecallFabric,
    AuthenticationError,
    RecallFabric,
    RecallFabricLlamaIndexRetriever,
    RecallFabricRetriever,
    TimeoutError,
    async_with_memory,
    with_memory,
)

from recallfabric.core.config import Settings
from recallfabric.main import create_app


# 1. Client Configuration and Environment Variables
def test_client_configuration(monkeypatch):
    monkeypatch.setenv("RECALLFABRIC_BASE_URL", "http://mycloud.com/api")
    monkeypatch.setenv("RECALLFABRIC_API_KEY", "rf_live_secret123")

    client = RecallFabric()
    assert client.base_url == "http://mycloud.com/api/v1"
    assert client.api_key == "rf_live_secret123"

    # Explicit override takes precedence
    custom_client = RecallFabric(base_url="http://custom.com", api_key="custom_key")
    assert custom_client.base_url == "http://custom.com/v1"
    assert custom_client.api_key == "custom_key"


# 2. Mocked Unit Tests: Core Methods
def test_mocked_remember_recall_forget():
    mem_id = str(uuid4())

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.endswith("/v1/remember") and request.method == "POST":
            assert request.headers.get("Idempotency-Key") == "test-key-1"
            body = json.loads(request.read())
            return httpx.Response(
                200,
                json={
                    "status": "created",
                    "action": "created",
                    "memory": {
                        "id": mem_id,
                        "user_id": body.get("user_id", "default_user"),
                        "content": body["content"],
                        "type": body["type"],
                        "importance": 0.8,
                        "confidence": 1.0,
                        "source": "sdk",
                        "version": 1,
                        "status": "active",
                    },
                    "count": 1,
                    "message": "Memory created successfully.",
                },
            )
        if url.endswith("/v1/recall") and request.method == "POST":
            return httpx.Response(
                200,
                json={
                    "context": "- [preference] User loves async Python",
                    "memories": [
                        {
                            "id": mem_id,
                            "user_id": "user_mock",
                            "content": "User loves async Python",
                            "type": "preference",
                            "importance": 0.8,
                            "confidence": 1.0,
                            "source": "sdk",
                            "version": 1,
                            "score": 0.85,
                            "similarity": 0.9,
                        }
                    ],
                    "count": 1,
                    "query": "python preference",
                },
            )
        if url.endswith("/v1/forget") and request.method == "POST":
            return httpx.Response(
                200,
                json={
                    "confirmed": True,
                    "status": "deleted",
                    "deleted_id": mem_id,
                    "message": "Memory deleted.",
                },
            )
        return httpx.Response(404, json={"detail": "Not found"})

    mock_http = httpx.Client(
        transport=httpx.MockTransport(handler), base_url="http://testserver/v1"
    )
    rf = RecallFabric(http_client=mock_http)

    # Remember
    rem_res = rf.remember(
        "User loves async Python",
        type="preference",
        idempotency_key="test-key-1",
    )
    assert rem_res.status == "created"
    assert rem_res.memory is not None
    assert rem_res.memory.content == "User loves async Python"

    # Recall
    rec_res = rf.recall("python preference")
    assert "User loves async Python" in rec_res.context
    assert rec_res.count == 1
    assert rec_res.memories[0].score == 0.85

    # Forget
    fog_res = rf.forget(memory_id=mem_id, confirm=True)
    assert fog_res.confirmed is True
    assert fog_res.deleted_id == mem_id


# 3. Retries with Backoff on 429 and 500
def test_retries_with_backoff_on_500_and_429():
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(
                500, json={"error": {"code": "INTERNAL", "message": "Server error"}}
            )
        if attempts == 2:
            return httpx.Response(
                429, json={"error": {"code": "RATE_LIMIT", "message": "Too many requests"}}
            )
        return httpx.Response(
            200,
            json={"service": "recallfabric", "service_version": "0.1.0", "api_version": "v1"},
        )

    mock_http = httpx.Client(
        transport=httpx.MockTransport(handler), base_url="http://testserver/v1"
    )
    rf = RecallFabric(http_client=mock_http, backoff_factor=0.01, max_retries=3)

    caps = rf.capabilities()
    assert caps.service == "recallfabric"
    assert attempts == 3  # Failed twice, succeeded on 3rd attempt


# 4. Auth Error Mapping
def test_auth_error_mapping():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401,
            json={"error": {"code": "UNAUTHORIZED", "message": "Invalid API token"}},
        )

    mock_http = httpx.Client(
        transport=httpx.MockTransport(handler), base_url="http://testserver/v1"
    )
    rf = RecallFabric(http_client=mock_http, max_retries=0)

    with pytest.raises(AuthenticationError) as exc_info:
        rf.capabilities()
    assert exc_info.value.status_code == 401
    assert "Invalid API token" in str(exc_info.value)


# 5. Timeout Error Handling
def test_timeout_error_handling():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("Timed out reading response")

    mock_http = httpx.Client(
        transport=httpx.MockTransport(handler), base_url="http://testserver/v1"
    )
    rf = RecallFabric(http_client=mock_http, max_retries=1, backoff_factor=0.01)

    with pytest.raises(TimeoutError) as exc_info:
        rf.capabilities()
    assert "timed out" in str(exc_info.value).lower()


# 6. Async Client Operations
@pytest.mark.anyio
async def test_async_client_operations():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "context": "- [profile] Staff Engineer",
                "memories": [],
                "count": 1,
                "query": "title",
            },
        )

    mock_http = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://testserver/v1"
    )
    async with AsyncRecallFabric(http_client=mock_http) as rf:
        res = await rf.recall("title")
        assert "Staff Engineer" in res.context


# 7. with_memory Sync Wrapper (Context Injection & Safe Background Extraction)
def test_with_memory_sync_wrapper():
    recalled = False
    extracted = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal recalled, extracted
        url = str(request.url)
        if url.endswith("/v1/recall"):
            recalled = True
            return httpx.Response(
                200,
                json={
                    "context": "- [preference] User prefers dark mode",
                    "memories": [],
                    "count": 1,
                    "query": "theme",
                },
            )
        if url.endswith("/v1/remember"):
            extracted = True
            return httpx.Response(200, json={"status": "extracted", "count": 1})
        return httpx.Response(200, json={})

    mock_http = httpx.Client(
        transport=httpx.MockTransport(handler), base_url="http://testserver/v1"
    )
    rf = RecallFabric(http_client=mock_http)

    def mock_chat_llm(messages: list[dict[str, str]]) -> str:
        # Verify that context was injected into system message
        assert messages[0]["role"] == "system"
        assert "User prefers dark mode" in messages[0]["content"]
        return "I will use dark mode theme for this design."

    wrapped_agent = with_memory(mock_chat_llm, rf, user_id="test_user")
    output = wrapped_agent([{"role": "user", "content": "What theme should we choose?"}])

    assert "I will use dark mode" in output
    assert recalled is True


# 8. async_with_memory Wrapper
@pytest.mark.anyio
async def test_async_with_memory_wrapper():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "context": "- [skill] Rust and Go specialist",
                "memories": [],
                "count": 1,
                "query": "skills",
            },
        )

    mock_http = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://testserver/v1"
    )
    rf = AsyncRecallFabric(http_client=mock_http)

    async def mock_async_llm(messages: list[dict[str, str]]) -> str:
        assert messages[0]["role"] == "system"
        assert "Rust and Go" in messages[0]["content"]
        return "Using Rust for the high-throughput worker."

    wrapped_agent = async_with_memory(mock_async_llm, rf, user_id="test_user")
    output = await wrapped_agent([{"role": "user", "content": "What language should we use?"}])
    assert "Using Rust" in output


# 9. Framework Adapters (LangChain & LlamaIndex)
def test_framework_adapters():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "context": "- [preference] User prefers tabs",
                "memories": [
                    {
                        "id": str(uuid4()),
                        "user_id": "user_adapt",
                        "content": "User prefers tabs over spaces",
                        "type": "preference",
                        "importance": 0.9,
                        "confidence": 1.0,
                        "source": "sdk",
                        "version": 1,
                        "score": 0.92,
                        "similarity": 0.95,
                    }
                ],
                "count": 1,
                "query": "indentation",
            },
        )

    mock_http = httpx.Client(
        transport=httpx.MockTransport(handler), base_url="http://testserver/v1"
    )
    rf = RecallFabric(http_client=mock_http)

    # LangChain Retriever
    lc_retriever = RecallFabricRetriever(client=rf, user_id="user_adapt")
    docs = lc_retriever.invoke("indentation")
    assert len(docs) == 1
    assert "User prefers tabs" in docs[0].page_content
    assert docs[0].metadata["type"] == "preference"

    # LlamaIndex Retriever
    li_retriever = RecallFabricLlamaIndexRetriever(client=rf, user_id="user_adapt")
    nodes = li_retriever.retrieve("indentation")
    assert len(nodes) == 1
    assert "User prefers tabs" in nodes[0].node.text
    assert nodes[0].score == 0.92


# 10. Integration Test with ASGI FastAPI Application
def test_integration_against_app_instance():
    """Acceptance test: 3 lines of code store and recall a memory."""
    from fastapi.testclient import TestClient

    settings = Settings(
        app_name="RecallFabric",
        environment="development",
        auth_enabled=False,
    )
    app = create_app(settings)

    with TestClient(app, base_url="http://testserver") as test_client:
        user_id = f"integration_user_{uuid4().hex[:6]}"
        rf = RecallFabric(base_url="http://testserver", http_client=test_client, user_id=user_id)

        # 3 lines of code acceptance:
        rem_res = rf.remember("User prefers Python and dark mode in all tools", type="preference")
        assert rem_res.status in ("created", "stored", "deduplicated")

        memories = rf.recall("editor preferences")
        assert "Python" in memories.context or "dark mode" in memories.context
        assert memories.count >= 1

        # Profile check
        prof = rf.profile()
        assert prof.user_id == user_id
        assert prof.memory_count >= 1

        # Capabilities check
        caps = rf.capabilities()
        assert caps.service == "recallfabric"
        assert caps.api_version == "v1"


@pytest.mark.anyio
async def test_async_integration_against_app_instance():
    from fastapi.testclient import TestClient

    settings = Settings(
        app_name="RecallFabric",
        environment="development",
        auth_enabled=False,
    )
    app = create_app(settings)

    with TestClient(app, base_url="http://testserver"):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver/v1"
        ) as async_http:
            user_id = f"async_integration_{uuid4().hex[:6]}"
            rf = AsyncRecallFabric(
                base_url="http://testserver", http_client=async_http, user_id=user_id
            )

            rem = await rf.remember("User is an expert in Kubernetes", type="skill")
            assert rem.status in ("created", "stored", "deduplicated")

            rec = await rf.recall("container orchestration")
            assert "Kubernetes" in rec.context
            assert rec.count >= 1
