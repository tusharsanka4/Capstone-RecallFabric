from typing import Any

from recallfabric.core.config import Settings
from recallfabric.providers.anthropic import AnthropicProvider
from recallfabric.providers.base import LLMProvider
from recallfabric.providers.gemini import GeminiProvider
from recallfabric.providers.ollama import OllamaProvider
from recallfabric.providers.openai import OpenAIProvider


def get_default_model_for_provider(
    provider_type: str,
    settings: Settings,
    task: str = "chat",
) -> str:
    ptype = provider_type.lower().strip()
    if ptype == "ollama":
        return settings.chat_model if task == "chat" else settings.extraction_model
    if ptype == "openai":
        return settings.openai_model
    if ptype == "anthropic":
        return settings.anthropic_model
    if ptype == "gemini":
        return settings.gemini_model
    return settings.chat_model


def get_provider(
    provider_type: str | None = None,
    model: str | None = None,
    settings: Settings | None = None,
    client: Any = None,
) -> LLMProvider:
    if settings is None:
        settings = Settings()
    ptype = (provider_type or settings.llm_provider).lower().strip()
    if ptype == "ollama":
        return OllamaProvider(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key.get_secret_value(),
            model=model or settings.chat_model,
            timeout=settings.llm_timeout,
            client=client,
        )
    if ptype == "openai":
        return OpenAIProvider(
            base_url=settings.openai_base_url,
            api_key=settings.openai_api_key.get_secret_value(),
            model=model or settings.openai_model,
            timeout=settings.llm_timeout,
            client=client,
        )
    if ptype == "anthropic":
        return AnthropicProvider(
            base_url=settings.anthropic_base_url,
            api_key=settings.anthropic_api_key.get_secret_value(),
            model=model or settings.anthropic_model,
            timeout=settings.llm_timeout,
            client=client,
        )
    if ptype == "gemini":
        return GeminiProvider(
            base_url=settings.gemini_base_url,
            api_key=settings.gemini_api_key.get_secret_value(),
            model=model or settings.gemini_model,
            timeout=settings.llm_timeout,
            client=client,
        )
    raise ValueError(f"Unknown LLM provider: {provider_type}")


def get_chat_provider(
    settings: Settings | None = None,
    client: Any = None,
) -> LLMProvider:
    if settings is None:
        settings = Settings()
    ptype = settings.chat_provider or settings.llm_provider
    model = get_default_model_for_provider(ptype, settings, task="chat")
    return get_provider(provider_type=ptype, model=model, settings=settings, client=client)


def get_extraction_provider(
    settings: Settings | None = None,
    client: Any = None,
) -> LLMProvider:
    if settings is None:
        settings = Settings()
    ptype = settings.extraction_provider or settings.llm_provider
    model = get_default_model_for_provider(ptype, settings, task="extraction")
    return get_provider(provider_type=ptype, model=model, settings=settings, client=client)
