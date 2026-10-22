"""Tests for Module C6: OpenAI-compatible memory proxy."""

from __future__ import annotations

import json
import json as _json
from collections.abc import Callable

import httpx
import pytest
from fastapi.testclient import TestClient

from recallfabric.core.config import Settings
from recallfabric.main import create_app


class MockUpstreamClient:
    def __init__(self, handler: Callable | None = None, **kwargs) -> None:
        self.handler = handler

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass

    async def aclose(self):
        pass

    def build_request(self, method, url, headers=None, json=None, **kwargs):
        content = _json.dumps(json).encode() if json is not None else b""
        return httpx.Request(method, url, headers=headers, content=content)

    async def send(self, req, stream=False, **kwargs):
        if self.handler:
            return await self.handler(req)
        return httpx.Response(200, json={"choices": []}, request=req)

    async def post(self, url, headers=None, json=None, **kwargs):
        req = self.build_request("POST", url, headers=headers, json=json)
        return await self.send(req)


@pytest.fixture
def proxy_app():
    settings = Settings(
        app_name="RecallFabric",
        environment="development",
        auth_enabled=False,
        proxy_allowed_upstreams=["https://api.openai.com", "https://api.anthropic.com"],
        proxy_default_upstream_url="https://api.openai.com/v1",
    )
    return create_app(settings)


@pytest.fixture
def client(proxy_app):
    with TestClient(proxy_app) as test_client:
        yield test_client


def test_proxy_context_injection_non_streaming(client, monkeypatch):
    """Test that proxy recalls relevant memory and injects it into system message."""
    captured_upstream_request = {}

    async def fake_handler(req):
        captured_upstream_request["headers"] = dict(req.headers)
        captured_upstream_request["body"] = json.loads(req.content.decode())
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-mock",
                "object": "chat.completion",
                "created": 1700000000,
                "model": "gpt-4o",
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "Hello! I remember you like Python.",
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"total_tokens": 42},
            },
            request=req,
        )

    monkeypatch.setattr(
        "recallfabric.api.proxy._resilient_recall",
        lambda req, uid, query, sett: "User prefers Python 3.12 and hates semicolons.",
    )
    monkeypatch.setattr(
        "recallfabric.api.proxy.httpx.AsyncClient",
        lambda **kwargs: MockUpstreamClient(handler=fake_handler, **kwargs),
    )

    payload = {
        "model": "gpt-4o",
        "messages": [{"role": "user", "content": "What language should I write this script in?"}],
        "stream": False,
    }

    resp = client.post(
        "/v1/proxy/chat/completions",
        json=payload,
        headers={"X-Upstream-Key": "sk-secret-upstream-key-12345"},
    )

    assert resp.status_code == 200
    resp_data = resp.json()
    assert resp_data["choices"][0]["message"]["content"] == "Hello! I remember you like Python."

    # Verify context injection into system message
    assert "body" in captured_upstream_request
    sent_messages = captured_upstream_request["body"]["messages"]
    assert sent_messages[0]["role"] == "system"
    assert "User prefers Python 3.12 and hates semicolons." in sent_messages[0]["content"]
    assert sent_messages[1]["role"] == "user"


def test_proxy_streaming_pass_through(client, monkeypatch):
    """Test that streaming SSE responses pass through unchanged."""
    sse_body = (
        b'data: {"choices": [{"delta": {"role": "assistant", "content": "Chunk 1"}}]}\n'
        b'data: {"choices": [{"delta": {"content": " Chunk 2"}}]}\n'
        b"data: [DONE]\n"
    )

    async def fake_handler(req):
        return httpx.Response(
            200,
            content=sse_body,
            headers={"content-type": "text/event-stream"},
            request=req,
        )

    monkeypatch.setattr(
        "recallfabric.api.proxy._resilient_recall",
        lambda req, uid, query, sett: "Test memory context",
    )
    monkeypatch.setattr(
        "recallfabric.api.proxy.httpx.AsyncClient",
        lambda **kwargs: MockUpstreamClient(handler=fake_handler, **kwargs),
    )

    payload = {
        "model": "gpt-4o",
        "messages": [{"role": "user", "content": "Tell me a joke"}],
        "stream": True,
    }

    resp = client.post("/v1/proxy/chat/completions", json=payload)
    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers.get("content-type", "")
    content_text = resp.text
    assert "Chunk 1" in content_text
    assert "Chunk 2" in content_text
    assert "data: [DONE]" in content_text


def test_proxy_memory_failure_never_blocks_upstream(client, monkeypatch):
    """Test that database or embedding failures in recall never block the chat completion."""

    def crash_recall(*args, **kwargs):
        raise RuntimeError("Postgres database is completely down!")

    # Force recall to crash
    monkeypatch.setattr("recallfabric.api.proxy.build_context", crash_recall)

    captured_sent_messages = []

    async def fake_handler(req):
        body = json.loads(req.content.decode())
        captured_sent_messages.extend(body.get("messages", []))
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-fallback",
                "object": "chat.completion",
                "choices": [{"message": {"role": "assistant", "content": "Upstream still works!"}}],
            },
            request=req,
        )

    monkeypatch.setattr(
        "recallfabric.api.proxy.httpx.AsyncClient",
        lambda **kwargs: MockUpstreamClient(handler=fake_handler, **kwargs),
    )

    payload = {
        "model": "gpt-4o",
        "messages": [{"role": "user", "content": "Hello world"}],
    }

    resp = client.post("/v1/proxy/chat/completions", json=payload)
    assert resp.status_code == 200
    assert resp.json()["choices"][0]["message"]["content"] == "Upstream still works!"
    # Ensure original message was forwarded unmodified despite memory failure
    assert len(captured_sent_messages) == 1
    assert captured_sent_messages[0]["content"] == "Hello world"


def test_proxy_upstream_keys_never_logged_or_stored(client, monkeypatch, caplog):
    """Test that upstream API keys are never written to logs or audit records."""

    async def fake_handler(req):
        return httpx.Response(200, json={"choices": []}, request=req)

    monkeypatch.setattr(
        "recallfabric.api.proxy.httpx.AsyncClient",
        lambda **kwargs: MockUpstreamClient(handler=fake_handler, **kwargs),
    )

    secret_key = "sk-super-secret-key-do-not-log-998877"

    with caplog.at_level("DEBUG"):
        resp = client.post(
            "/v1/proxy/chat/completions",
            json={"messages": [{"role": "user", "content": "hi"}]},
            headers={"X-Upstream-Key": secret_key},
        )

    assert resp.status_code == 200
    # Verify the secret key does not appear anywhere in captured log text
    assert secret_key not in caplog.text


def test_proxy_allowlist_enforcement(client):
    """Test that unauthorized upstream destinations are rejected with 403."""
    payload = {"messages": [{"role": "user", "content": "hi"}]}

    resp = client.post(
        "/v1/proxy/chat/completions",
        json=payload,
        headers={"X-Upstream-URL": "https://malicious-site.evil.com/v1"},
    )

    assert resp.status_code == 403
    assert "not permitted by RecallFabric proxy allowlist" in resp.json()["error"]["message"]


def test_openai_sdk_compatibility(client, monkeypatch):
    """Verify an OpenAI-SDK style request works seamlessly with the proxy."""

    async def fake_handler(req):
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-sdk-compat",
                "object": "chat.completion",
                "created": 1700000001,
                "model": "gpt-4o-mini",
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "SDK compatibility verified.",
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            },
            request=req,
        )

    monkeypatch.setattr(
        "recallfabric.api.proxy.httpx.AsyncClient",
        lambda **kwargs: MockUpstreamClient(handler=fake_handler, **kwargs),
    )
    monkeypatch.setattr(
        "recallfabric.api.proxy._resilient_recall",
        lambda req, uid, query, sett: "User preference: succinct answers.",
    )

    # Calling unversioned alias /proxy/chat/completions (OpenAI SDK with base_url="http://host/proxy")
    resp = client.post(
        "/proxy/chat/completions",
        json={
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": "Verify SDK"}],
            "temperature": 0.7,
        },
        headers={
            "Authorization": "Bearer sk-test-upstream-key",
            "X-RecallFabric-Key": "rf_mock_key",
        },
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["choices"][0]["message"]["content"] == "SDK compatibility verified."
