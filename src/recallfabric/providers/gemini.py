from typing import Any

import httpx

from recallfabric.providers.base import (
    LLMProvider,
    ProviderBadResponse,
    ProviderResponse,
    ProviderTimeout,
    ProviderUnavailable,
)


class GeminiProvider(LLMProvider):
    name = "gemini"

    def __init__(
        self,
        base_url: str = "https://generativelanguage.googleapis.com/v1beta",
        api_key: str = "",
        model: str = "gemini-1.5-flash",
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
            raise ProviderUnavailable("Gemini API key not configured")

        system_instruction: dict[str, Any] | None = None
        contents: list[dict[str, Any]] = []

        for m in messages:
            role = m.get("role", "user")
            content = m.get("content", "")
            if role == "system":
                system_instruction = {"parts": [{"text": content}]}
            else:
                gemini_role = "user" if role == "user" else "model"
                contents.append({"role": gemini_role, "parts": [{"text": content}]})

        generation_config: dict[str, Any] = {"temperature": temperature}
        if max_tokens is not None:
            generation_config["maxOutputTokens"] = max_tokens
        if json_mode:
            generation_config["responseMimeType"] = "application/json"

        payload: dict[str, Any] = {
            "contents": contents,
            "generationConfig": generation_config,
        }
        if system_instruction:
            payload["systemInstruction"] = system_instruction

        headers = {
            "x-goog-api-key": self.api_key,
            "content-type": "application/json",
        }

        try:
            r = self.client.post(
                f"{self.base_url}/models/{self.model}:generateContent",
                headers=headers,
                json=payload,
            )
        except httpx.TimeoutException as e:
            raise ProviderTimeout("Gemini request timed out") from e
        except httpx.ConnectError as e:
            raise ProviderUnavailable("Gemini service unreachable") from e
        except Exception as e:
            err_msg = str(e).lower()
            if "timeout" in err_msg:
                raise ProviderTimeout("Gemini request timed out") from e
            if "connect" in err_msg or "unreachable" in err_msg:
                raise ProviderUnavailable("Gemini service unreachable") from e
            raise ProviderBadResponse(f"Gemini request failed: {e}") from e

        if r.status_code in (503, 504):
            if r.status_code == 504:
                raise ProviderTimeout("Gemini request timed out")
            raise ProviderUnavailable("Gemini service unavailable")
        if r.status_code >= 400:
            raise ProviderBadResponse(f"Gemini error HTTP {r.status_code}: {r.text}")

        try:
            data = r.json()
            candidates = data.get("candidates", [])
            if not candidates:
                raise ProviderBadResponse("Gemini returned no candidates")
            parts = candidates[0].get("content", {}).get("parts", [])
            if not parts:
                raise ProviderBadResponse("Gemini returned empty parts")
            text = parts[0].get("text", "")
            return ProviderResponse(text.strip(), name=self.name, model=self.model)
        except Exception as e:
            if isinstance(e, (ProviderBadResponse, ProviderTimeout, ProviderUnavailable)):
                raise
            raise ProviderBadResponse(f"Failed to parse Gemini response: {e}") from e

    def is_available(self) -> bool:
        return bool(self.api_key)
