from typing import Any

import httpx
from openai import APIConnectionError, APITimeoutError, OpenAI

from recallfabric.providers.base import (
    LLMProvider,
    ProviderBadResponse,
    ProviderResponse,
    ProviderTimeout,
    ProviderUnavailable,
)


class OllamaProvider(LLMProvider):
    name = "ollama"

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:11434/v1",
        api_key: str = "ollama",
        model: str = "qwen2.5:0.5b",
        timeout: float = 30.0,
        client: Any | None = None,
    ):
        self.base_url = base_url
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self._client = client

    @property
    def client(self) -> Any:
        if self._client is None:
            self._client = OpenAI(
                base_url=self.base_url,
                api_key=self.api_key,
                timeout=self.timeout,
            )
        return self._client

    def chat(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.0,
        max_tokens: int | None = None,
        json_mode: bool = False,
    ) -> str:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        try:
            response = self.client.chat.completions.create(**kwargs)
        except APITimeoutError as e:
            raise ProviderTimeout("LLM request timed out") from e
        except APIConnectionError as e:
            raise ProviderUnavailable("LLM service unreachable") from e
        except Exception as e:
            err_msg = str(e).lower()
            if "timeout" in err_msg or "timed out" in err_msg:
                raise ProviderTimeout("LLM request timed out") from e
            if "connect" in err_msg or "unreachable" in err_msg:
                raise ProviderUnavailable("LLM service unreachable") from e
            raise ProviderBadResponse(f"LLM request failed: {e}") from e

        choices = getattr(response, "choices", None)
        if not choices:
            raise ProviderBadResponse("LLM returned no choices")
        message = getattr(choices[0], "message", None)
        content = getattr(message, "content", None)
        if content is None:
            raise ProviderBadResponse("LLM returned empty content")
        return ProviderResponse(content.strip(), name=self.name, model=self.model)

    def is_available(self) -> bool:
        try:
            tags_url = self.base_url.removesuffix("/v1") + "/api/tags"
            r = httpx.get(tags_url, timeout=2.0)
            return r.status_code == 200
        except Exception:
            return False
