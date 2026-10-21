import json
from unittest.mock import MagicMock

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from recallfabric.api.chat import get_llm_client as get_chat_llm_client
from recallfabric.api.extraction import get_llm_client as get_extract_llm_client
from recallfabric.core.config import Settings
from recallfabric.embeddings.service import EmbeddingResult, get_embedding_provider
from recallfabric.main import create_app
from recallfabric.providers import (
    AnthropicProvider,
    GeminiProvider,
    LLMProvider,
    OllamaProvider,
    OpenAIProvider,
    ProviderBadResponse,
    ProviderResponse,
    ProviderTimeout,
    ProviderUnavailable,
    get_chat_provider,
    get_extraction_provider,
    get_provider,
)


class DummyEmbedder:
    model_id = "test-embedder"
    dimensions = 3

    def embed(self, text, kind="passage"):
        return EmbeddingResult(model=self.model_id, dimensions=3, vector=[1.0, 0.0, 0.0])


class FakeProvider(LLMProvider):
    name = "fake"
    model = "fake-model-v1"

    def __init__(self, response_text: str = ""):
        self.response_text = response_text
        self.calls: list[dict] = []

    def chat(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.0,
        max_tokens: int | None = None,
        json_mode: bool = False,
    ) -> str:
        self.calls.append(
            {
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "json_mode": json_mode,
            }
        )
        return ProviderResponse(self.response_text, name=self.name, model=self.model)

    def is_available(self) -> bool:
        return True


def test_provider_response_properties():
    res = ProviderResponse("hello world", name="test-name", model="test-model")
    assert res == "hello world"
    assert res.text == "hello world"
    assert res.name == "test-name"
    assert res.model == "test-model"
    assert isinstance(res, str)


def test_provider_factory_and_settings_selection():
    settings = Settings(
        _env_file=None,
        llm_provider="ollama",
        chat_model="qwen-chat",
        extraction_model="qwen-extract",
    )
    p_chat = get_chat_provider(settings)
    assert isinstance(p_chat, OllamaProvider)
    assert p_chat.model == "qwen-chat"

    p_extract = get_extraction_provider(settings)
    assert isinstance(p_extract, OllamaProvider)
    assert p_extract.model == "qwen-extract"

    custom_settings = Settings(
        _env_file=None,
        llm_provider="ollama",
        chat_provider="openai",
        extraction_provider="anthropic",
        openai_api_key=SecretStr("sk-test"),
        anthropic_api_key=SecretStr("ant-test"),
    )
    p_chat_custom = get_chat_provider(custom_settings)
    assert isinstance(p_chat_custom, OpenAIProvider)

    p_extract_custom = get_extraction_provider(custom_settings)
    assert isinstance(p_extract_custom, AnthropicProvider)

    gemini_prov = get_provider(
        provider_type="gemini",
        settings=Settings(_env_file=None, gemini_api_key=SecretStr("gem-test")),
    )
    assert isinstance(gemini_prov, GeminiProvider)

    with pytest.raises(ValueError):
        get_provider(provider_type="unsupported")


def test_acceptance_switching_llm_provider_env():
    settings_ollama = Settings(_env_file=None, llm_provider="ollama")
    assert get_chat_provider(settings_ollama).name == "ollama"

    settings_openai = Settings(
        _env_file=None,
        llm_provider="openai",
        openai_api_key=SecretStr("key"),
        openai_model="gpt-4o",
    )
    prov_openai = get_chat_provider(settings_openai)
    assert prov_openai.name == "openai"
    assert prov_openai.model == "gpt-4o"

    settings_anthropic = Settings(
        _env_file=None,
        llm_provider="anthropic",
        anthropic_api_key=SecretStr("key"),
        anthropic_model="claude-3-sonnet",
    )
    prov_anthropic = get_chat_provider(settings_anthropic)
    assert prov_anthropic.name == "anthropic"
    assert prov_anthropic.model == "claude-3-sonnet"

    settings_gemini = Settings(
        _env_file=None,
        llm_provider="gemini",
        gemini_api_key=SecretStr("key"),
        gemini_model="gemini-1.5-pro",
    )
    prov_gemini = get_chat_provider(settings_gemini)
    assert prov_gemini.name == "gemini"
    assert prov_gemini.model == "gemini-1.5-pro"


def test_fake_provider_drives_chat_and_extraction():
    fake_reply = "I am a helpful assistant from fake provider."
    fake_extract = (
        '{"memories": [{"content": "User prefers Earl Grey tea", "type": "preference", '
        '"importance": 0.8, "confidence": 0.95, "creation_reason": "Direct user statement"}]}'
    )

    chat_fake = FakeProvider(response_text=fake_reply)
    extract_fake = FakeProvider(response_text=fake_extract)

    app = create_app(Settings(_env_file=None))
    app.state.embedding_provider = DummyEmbedder()
    app.dependency_overrides[get_embedding_provider] = lambda: DummyEmbedder()
    app.dependency_overrides[get_chat_llm_client] = lambda: chat_fake
    app.dependency_overrides[get_extract_llm_client] = lambda: extract_fake

    from recallfabric.db.session import get_session

    mock_session = MagicMock()
    mock_session.execute.return_value.all.return_value = []
    mock_session.begin.return_value.__enter__.return_value = None
    mock_session.begin.return_value.__exit__.return_value = None
    app.dependency_overrides[get_session] = lambda: mock_session

    with TestClient(app) as client:
        chat_res = client.post(
            "/chat",
            json={"user_id": "test_user", "message": "Hi there!"},
        )
        assert chat_res.status_code == 200
        assert chat_res.json()["reply"] == fake_reply
        assert chat_res.json()["model"] == "fake-model-v1"
        assert len(chat_fake.calls) == 1

        ext_res = client.post(
            "/extraction",
            json={
                "user_id": "test_user",
                "text": "I really enjoy drinking Earl Grey tea.",
                "source": "dialogue_1",
                "dry_run": True,
            },
        )
        assert ext_res.status_code == 201
        assert len(ext_res.json()["candidates"]) == 1
        assert ext_res.json()["candidates"][0]["content"] == "User prefers Earl Grey tea"
        assert len(extract_fake.calls) == 1


def test_ollama_provider_adapter():
    mock_client = MagicMock()
    mock_choice = MagicMock()
    mock_choice.message.content = "Ollama response"
    mock_client.chat.completions.create.return_value = MagicMock(choices=[mock_choice])

    provider = OllamaProvider(model="qwen-test", client=mock_client)
    res = provider.chat([{"role": "user", "content": "hi"}], json_mode=True)
    assert res == "Ollama response"
    assert res.name == "ollama"
    assert res.model == "qwen-test"

    mock_client.chat.completions.create.side_effect = Exception("connection timeout")
    with pytest.raises(ProviderTimeout):
        provider.chat([{"role": "user", "content": "hi"}])

    mock_client.chat.completions.create.side_effect = Exception("connection refused unreachable")
    with pytest.raises(ProviderUnavailable):
        provider.chat([{"role": "user", "content": "hi"}])

    mock_client.chat.completions.create.side_effect = Exception("unsupported format error")
    with pytest.raises(ProviderBadResponse):
        provider.chat([{"role": "user", "content": "hi"}])


def test_openai_provider_adapter():
    provider_no_key = OpenAIProvider(api_key="")
    with pytest.raises(ProviderUnavailable):
        provider_no_key.chat([{"role": "user", "content": "hi"}])

    mock_client = MagicMock()
    mock_choice = MagicMock()
    mock_choice.message.content = "OpenAI answer"
    mock_client.chat.completions.create.return_value = MagicMock(choices=[mock_choice])

    provider = OpenAIProvider(api_key="sk-test", model="gpt-4o", client=mock_client)
    res = provider.chat([{"role": "user", "content": "hello"}], json_mode=True, max_tokens=100)
    assert res == "OpenAI answer"
    assert res.model == "gpt-4o"

    call_kwargs = mock_client.chat.completions.create.call_args[1]
    assert call_kwargs["response_format"] == {"type": "json_object"}
    assert call_kwargs["max_tokens"] == 100

    mock_client.chat.completions.create.side_effect = Exception("timed out")
    with pytest.raises(ProviderTimeout):
        provider.chat([{"role": "user", "content": "hi"}])


def test_anthropic_provider_adapter():
    provider_no_key = AnthropicProvider(api_key="")
    with pytest.raises(ProviderUnavailable):
        provider_no_key.chat([{"role": "user", "content": "hi"}])

    captured_requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_requests.append(request)
        body = json.loads(request.content)
        assert body["model"] == "claude-3-haiku-20240307"
        assert "system" in body
        assert request.headers["x-api-key"] == "ant-secret"
        assert request.headers["anthropic-version"] == "2023-06-01"
        return httpx.Response(
            200,
            json={
                "id": "msg_123",
                "type": "message",
                "role": "assistant",
                "content": [{"type": "text", "text": "Claude answer"}],
            },
        )

    mock_http = httpx.Client(transport=httpx.MockTransport(handler))
    provider = AnthropicProvider(api_key="ant-secret", client=mock_http)
    res = provider.chat(
        [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Say hi"},
        ],
        json_mode=True,
    )
    assert res == "Claude answer"
    assert res.name == "anthropic"

    def timeout_handler(request: httpx.Request):
        raise httpx.ReadTimeout("read timed out")

    timeout_provider = AnthropicProvider(
        api_key="ant-secret",
        client=httpx.Client(transport=httpx.MockTransport(timeout_handler)),
    )
    with pytest.raises(ProviderTimeout):
        timeout_provider.chat([{"role": "user", "content": "hi"}])

    def overload_handler(request: httpx.Request):
        return httpx.Response(529, text="Overloaded")

    overload_provider = AnthropicProvider(
        api_key="ant-secret",
        client=httpx.Client(transport=httpx.MockTransport(overload_handler)),
    )
    with pytest.raises(ProviderUnavailable):
        overload_provider.chat([{"role": "user", "content": "hi"}])

    def bad_handler(request: httpx.Request):
        return httpx.Response(400, text="Bad Request")

    bad_provider = AnthropicProvider(
        api_key="ant-secret",
        client=httpx.Client(transport=httpx.MockTransport(bad_handler)),
    )
    with pytest.raises(ProviderBadResponse):
        bad_provider.chat([{"role": "user", "content": "hi"}])


def test_gemini_provider_adapter():
    provider_no_key = GeminiProvider(api_key="")
    with pytest.raises(ProviderUnavailable):
        provider_no_key.chat([{"role": "user", "content": "hi"}])

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert request.headers["x-goog-api-key"] == "gem-secret"
        assert body["generationConfig"]["responseMimeType"] == "application/json"
        assert body["contents"][0]["role"] == "user"
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "content": {
                            "parts": [{"text": '{"result": "Gemini response"}'}],
                            "role": "model",
                        }
                    }
                ]
            },
        )

    mock_http = httpx.Client(transport=httpx.MockTransport(handler))
    provider = GeminiProvider(api_key="gem-secret", client=mock_http)
    res = provider.chat(
        [
            {"role": "system", "content": "Act as an extractor."},
            {"role": "user", "content": "Give me JSON."},
        ],
        json_mode=True,
    )
    assert res == '{"result": "Gemini response"}'
    assert res.name == "gemini"

    def timeout_handler(request: httpx.Request):
        raise httpx.ConnectTimeout("connect timed out")

    timeout_provider = GeminiProvider(
        api_key="gem-secret",
        client=httpx.Client(transport=httpx.MockTransport(timeout_handler)),
    )
    with pytest.raises(ProviderTimeout):
        timeout_provider.chat([{"role": "user", "content": "hi"}])

    def unavailable_handler(request: httpx.Request):
        return httpx.Response(503, text="Service Unavailable")

    unavail_provider = GeminiProvider(
        api_key="gem-secret",
        client=httpx.Client(transport=httpx.MockTransport(unavailable_handler)),
    )
    with pytest.raises(ProviderUnavailable):
        unavail_provider.chat([{"role": "user", "content": "hi"}])


def test_get_providers_endpoint():
    app = create_app(
        Settings(
            _env_file=None,
            llm_provider="ollama",
            chat_provider="openai",
            openai_api_key=SecretStr("sk-secret"),
            anthropic_api_key=SecretStr(""),
        )
    )
    client = TestClient(app)

    res = client.get("/providers")
    assert res.status_code == 200
    data = res.json()
    assert data["default_provider"] == "ollama"
    assert data["chat_provider"] == "openai"
    assert data["extraction_provider"] == "ollama"

    providers = {p["name"]: p for p in data["providers"]}
    assert "ollama" in providers
    assert "openai" in providers
    assert "anthropic" in providers
    assert "gemini" in providers

    assert providers["openai"]["configured"] is True
    assert providers["anthropic"]["configured"] is False

    raw_text = res.text
    assert "sk-secret" not in raw_text
    assert "api_key" not in raw_text.lower()
