from typing import Any

import httpx

from recallfabric.providers.base import (
    LLMProvider,
    ProviderBadResponse,
    ProviderResponse,
    ProviderTimeout,
    ProviderUnavailable,
)


class AnthropicProvider(LLMProvider):
    name = "anthropic"

    def __init__(
        self,
        base_url: str = "https://api.anthropic.com",
        api_key: str = "",
        model: str = "claude-3-haiku-20240307",
        timeout: float = 30.0,
        client: httpx.Client | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self._client = client

    @property
    def client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(timeout=self.timeout)
        return self._client

    def chat(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.0,
        max_tokens: int | None = None,
        json_mode: bool = False,
    ) -> str:
        if not self.api_key:
            raise ProviderUnavailable("Anthropic API key not configured")

        system_parts: list[str] = []
        anthropic_msgs: list[dict[str, str]] = []

        for m in messages:
            role = m.get("role", "user")
            content = m.get("content", "")
            if role == "system":
                system_parts.append(content)
            elif role in ("user", "assistant"):
                anthropic_msgs.append({"role": role, "content": content})

        if json_mode:
            system_parts.append(
                "Respond strictly with valid JSON only. "
                "Do not include markdown formatting or conversational filler."
            )

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": anthropic_msgs,
            "max_tokens": max_tokens or 1024,
            "temperature": temperature,
        }
        if system_parts:
            payload["system"] = "\n\n".join(system_parts)

        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

        try:
            r = self.client.post(
                f"{self.base_url}/v1/messages",
                headers=headers,
                json=payload,
            )
        except httpx.TimeoutException as e:
            raise ProviderTimeout("Anthropic request timed out") from e
        except httpx.ConnectError as e:
            raise ProviderUnavailable("Anthropic service unreachable") from e
        except Exception as e:
            err_msg = str(e).lower()
            if "timeout" in err_msg:
                raise ProviderTimeout("Anthropic request timed out") from e
            if "connect" in err_msg or "unreachable" in err_msg:
                raise ProviderUnavailable("Anthropic service unreachable") from e
            raise ProviderBadResponse(f"Anthropic request failed: {e}") from e

        if r.status_code in (503, 529):
            raise ProviderUnavailable("Anthropic service unavailable or overloaded")
        if r.status_code == 408 or r.status_code == 504:
            raise ProviderTimeout("Anthropic request timed out")
        if r.status_code >= 400:
            raise ProviderBadResponse(f"Anthropic error HTTP {r.status_code}: {r.text}")

        try:
            data = r.json()
            blocks = data.get("content", [])
            text_parts = [
                b["text"] for b in blocks if isinstance(b, dict) and b.get("type") == "text"
            ]
            content = "".join(text_parts).strip()
            if not content:
                raise ProviderBadResponse("Anthropic returned empty content")
            return ProviderResponse(content, name=self.name, model=self.model)
        except Exception as e:
            if isinstance(e, (ProviderBadResponse, ProviderTimeout, ProviderUnavailable)):
                raise
            raise ProviderBadResponse(f"Failed to parse Anthropic response: {e}") from e

    def is_available(self) -> bool:
        return bool(self.api_key)
