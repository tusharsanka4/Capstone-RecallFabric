"""RecallFabric synchronous and asynchronous HTTP clients."""

from __future__ import annotations

import os
import time
from typing import Any
from uuid import UUID

import httpx

from recallfabric_client.exceptions import (
    APIError,
    AuthenticationError,
    ConnectionError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
    RecallFabricError,
    TimeoutError,
)
from recallfabric_client.models import (
    CapabilitiesResult,
    ForgetResult,
    Memory,
    MemoryType,
    ProfileResult,
    RecallResult,
    RememberResult,
)

RETRY_STATUS_CODES = {429, 500, 502, 503, 504}


def _resolve_base_url(base_url: str | None) -> str:
    url = (base_url or os.getenv("RECALLFABRIC_BASE_URL") or "http://localhost:8000").rstrip("/")
    if not url.endswith("/v1"):
        url = f"{url}/v1"
    return url


def _resolve_api_key(api_key: str | None) -> str | None:
    return api_key or os.getenv("RECALLFABRIC_API_KEY")


def _handle_error_response(response: httpx.Response) -> None:
    status_code = response.status_code
    code = "API_ERROR"
    message = response.text

    try:
        data = response.json()
        if isinstance(data, dict):
            if "error" in data and isinstance(data["error"], dict):
                code = str(data["error"].get("code", "API_ERROR"))
                message = str(data["error"].get("message", response.text))
            elif "detail" in data:
                detail = data["detail"]
                message = str(detail) if not isinstance(detail, list) else str(detail)
    except Exception:
        pass

    if status_code == 401:
        raise AuthenticationError(message=message, details=response.text)
    if status_code == 403:
        raise PermissionDeniedError(message=message, details=response.text)
    if status_code == 404:
        raise NotFoundError(message=message, details=response.text)
    if status_code == 429:
        raise RateLimitError(message=message, details=response.text)

    raise APIError(status_code=status_code, message=message, code=code, details=response.text)


class RecallFabric:
    """Synchronous client for RecallFabric."""

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        user_id: str | None = None,
        timeout: float = 15.0,
        max_retries: int = 3,
        backoff_factor: float = 0.5,
        http_client: httpx.Client | None = None,
    ) -> None:
        self.base_url = _resolve_base_url(base_url)
        self.api_key = _resolve_api_key(api_key)
        self.user_id = user_id
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor

        headers = {
            "Content-Type": "application/json",
            "User-Agent": "recallfabric-python-client/0.1.0",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        self._client = http_client or httpx.Client(
            base_url=self.base_url,
            headers=headers,
            timeout=self.timeout,
        )
        self._owns_client = http_client is None

    def __enter__(self) -> RecallFabric:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def _request(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        url = path if path.startswith("http") else f"{self.base_url}{path}"
        req_headers = dict(headers or {})

        for attempt in range(self.max_retries + 1):
            try:
                resp = self._client.request(
                    method=method,
                    url=url,
                    json=json,
                    params=params,
                    headers=req_headers if req_headers else None,
                )
                if resp.status_code in RETRY_STATUS_CODES and attempt < self.max_retries:
                    delay = self.backoff_factor * (2**attempt)
                    time.sleep(delay)
                    continue

                if resp.is_error:
                    _handle_error_response(resp)

                if resp.status_code == 204:
                    return None
                return resp.json()

            except httpx.TimeoutException as exc:
                if attempt < self.max_retries:
                    time.sleep(self.backoff_factor * (2**attempt))
                    continue
                raise TimeoutError(f"Request to {url} timed out: {exc}") from exc
            except httpx.TransportError as exc:
                if attempt < self.max_retries:
                    time.sleep(self.backoff_factor * (2**attempt))
                    continue
                raise ConnectionError(f"Connection error requesting {url}: {exc}") from exc

        raise RecallFabricError("Max retries exceeded without a response")

    def remember(
        self,
        content: str | None = None,
        *,
        text: str | None = None,
        type: MemoryType = "fact",
        importance: float | None = None,
        confidence: float = 1.0,
        source: str = "sdk",
        extract: bool = False,
        user_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> RememberResult:
        """Store an explicit memory statement or extract facts from conversation."""
        payload: dict[str, Any] = {
            "type": type,
            "confidence": confidence,
            "source": source,
            "extract": extract,
        }
        if content is not None:
            payload["content"] = content
        if text is not None:
            payload["text"] = text
        if content is None and text is None:
            raise ValueError("Either 'content' or 'text' must be provided.")

        if importance is not None:
            payload["importance"] = importance
        uid = user_id or self.user_id
        if uid:
            payload["user_id"] = uid
        if metadata:
            payload["metadata"] = metadata

        headers = {}
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key

        data = self._request("POST", "/remember", json=payload, headers=headers)
        return RememberResult.model_validate(data)

    def recall(
        self,
        query: str,
        *,
        limit: int = 5,
        type: MemoryType | None = None,
        min_similarity: float | None = None,
        user_id: str | None = None,
    ) -> RecallResult:
        """Retrieve memories ranked by multi-factor relevance with formatted context."""
        payload: dict[str, Any] = {
            "query": query,
            "limit": limit,
        }
        if type:
            payload["type"] = type
        if min_similarity is not None:
            payload["min_similarity"] = min_similarity
        uid = user_id or self.user_id
        if uid:
            payload["user_id"] = uid

        data = self._request("POST", "/recall", json=payload)
        return RecallResult.model_validate(data)

    def forget(
        self,
        *,
        memory_id: str | UUID | None = None,
        query: str | None = None,
        confirm: bool = False,
        user_id: str | None = None,
    ) -> ForgetResult:
        """Delete a memory by UUID or semantic match with confirmation flow."""
        payload: dict[str, Any] = {"confirm": confirm}
        if memory_id is not None:
            payload["memory_id"] = str(memory_id)
        if query is not None:
            payload["query"] = query
        uid = user_id or self.user_id
        if uid:
            payload["user_id"] = uid

        data = self._request("POST", "/forget", json=payload)
        return ForgetResult.model_validate(data)

    def profile(
        self,
        *,
        user_id: str | None = None,
        limit: int = 20,
    ) -> ProfileResult:
        """Retrieve compact markdown profile summary and categorized active memories."""
        params: dict[str, Any] = {"limit": limit}
        uid = user_id or self.user_id
        if uid:
            params["user_id"] = uid

        data = self._request("GET", "/profile", params=params)
        return ProfileResult.model_validate(data)

    def capabilities(self) -> CapabilitiesResult:
        """Inspect service version, active models, supported types, and limits."""
        data = self._request("GET", "/capabilities")
        return CapabilitiesResult.model_validate(data)

    def list(
        self,
        *,
        user_id: str | None = None,
        status: str = "active",
        type: MemoryType | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Memory]:
        """List user memories."""
        params: dict[str, Any] = {
            "status": status,
            "limit": limit,
            "offset": offset,
        }
        uid = user_id or self.user_id
        if uid:
            params["user_id"] = uid
        if type:
            params["type"] = type

        data = self._request("GET", "/memories", params=params)
        return [Memory.model_validate(item) for item in data]

    def update(
        self,
        memory_id: str | UUID,
        *,
        content: str | None = None,
        type: MemoryType | None = None,
        importance: float | None = None,
        user_id: str | None = None,
    ) -> Memory:
        """Update an existing memory's content, type, or importance."""
        payload: dict[str, Any] = {}
        if content is not None:
            payload["content"] = content
        if type is not None:
            payload["type"] = type
        if importance is not None:
            payload["importance"] = importance

        params: dict[str, Any] = {}
        uid = user_id or self.user_id
        if uid:
            params["user_id"] = uid

        data = self._request("PATCH", f"/memories/{memory_id}", json=payload, params=params)
        return Memory.model_validate(data)


class AsyncRecallFabric:
    """Asynchronous client for RecallFabric."""

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        user_id: str | None = None,
        timeout: float = 15.0,
        max_retries: int = 3,
        backoff_factor: float = 0.5,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = _resolve_base_url(base_url)
        self.api_key = _resolve_api_key(api_key)
        self.user_id = user_id
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor

        headers = {
            "Content-Type": "application/json",
            "User-Agent": "recallfabric-python-client/0.1.0",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        self._client = http_client or httpx.AsyncClient(
            base_url=self.base_url,
            headers=headers,
            timeout=self.timeout,
        )
        self._owns_client = http_client is None

    async def __aenter__(self) -> AsyncRecallFabric:
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        await self.close()

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        import asyncio

        url = path if path.startswith("http") else f"{self.base_url}{path}"
        req_headers = dict(headers or {})

        for attempt in range(self.max_retries + 1):
            try:
                resp = await self._client.request(
                    method=method,
                    url=url,
                    json=json,
                    params=params,
                    headers=req_headers if req_headers else None,
                )
                if resp.status_code in RETRY_STATUS_CODES and attempt < self.max_retries:
                    delay = self.backoff_factor * (2**attempt)
                    await asyncio.sleep(delay)
                    continue

                if resp.is_error:
                    _handle_error_response(resp)

                if resp.status_code == 204:
                    return None
                return resp.json()

            except httpx.TimeoutException as exc:
                if attempt < self.max_retries:
                    await asyncio.sleep(self.backoff_factor * (2**attempt))
                    continue
                raise TimeoutError(f"Request to {url} timed out: {exc}") from exc
            except httpx.TransportError as exc:
                if attempt < self.max_retries:
                    await asyncio.sleep(self.backoff_factor * (2**attempt))
                    continue
                raise ConnectionError(f"Connection error requesting {url}: {exc}") from exc

        raise RecallFabricError("Max retries exceeded without a response")

    async def remember(
        self,
        content: str | None = None,
        *,
        text: str | None = None,
        type: MemoryType = "fact",
        importance: float | None = None,
        confidence: float = 1.0,
        source: str = "sdk",
        extract: bool = False,
        user_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> RememberResult:
        """Store an explicit memory statement or extract facts asynchronously."""
        payload: dict[str, Any] = {
            "type": type,
            "confidence": confidence,
            "source": source,
            "extract": extract,
        }
        if content is not None:
            payload["content"] = content
        if text is not None:
            payload["text"] = text
        if content is None and text is None:
            raise ValueError("Either 'content' or 'text' must be provided.")

        if importance is not None:
            payload["importance"] = importance
        uid = user_id or self.user_id
        if uid:
            payload["user_id"] = uid
        if metadata:
            payload["metadata"] = metadata

        headers = {}
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key

        data = await self._request("POST", "/remember", json=payload, headers=headers)
        return RememberResult.model_validate(data)

    async def recall(
        self,
        query: str,
        *,
        limit: int = 5,
        type: MemoryType | None = None,
        min_similarity: float | None = None,
        user_id: str | None = None,
    ) -> RecallResult:
        """Retrieve memories ranked by multi-factor relevance asynchronously."""
        payload: dict[str, Any] = {
            "query": query,
            "limit": limit,
        }
        if type:
            payload["type"] = type
        if min_similarity is not None:
            payload["min_similarity"] = min_similarity
        uid = user_id or self.user_id
        if uid:
            payload["user_id"] = uid

        data = await self._request("POST", "/recall", json=payload)
        return RecallResult.model_validate(data)

    async def forget(
        self,
        *,
        memory_id: str | UUID | None = None,
        query: str | None = None,
        confirm: bool = False,
        user_id: str | None = None,
    ) -> ForgetResult:
        """Delete a memory asynchronously with confirmation flow."""
        payload: dict[str, Any] = {"confirm": confirm}
        if memory_id is not None:
            payload["memory_id"] = str(memory_id)
        if query is not None:
            payload["query"] = query
        uid = user_id or self.user_id
        if uid:
            payload["user_id"] = uid

        data = await self._request("POST", "/forget", json=payload)
        return ForgetResult.model_validate(data)

    async def profile(
        self,
        *,
        user_id: str | None = None,
        limit: int = 20,
    ) -> ProfileResult:
        """Retrieve profile summary and categorized active memories asynchronously."""
        params: dict[str, Any] = {"limit": limit}
        uid = user_id or self.user_id
        if uid:
            params["user_id"] = uid

        data = await self._request("GET", "/profile", params=params)
        return ProfileResult.model_validate(data)

    async def capabilities(self) -> CapabilitiesResult:
        """Inspect service capabilities asynchronously."""
        data = await self._request("GET", "/capabilities")
        return CapabilitiesResult.model_validate(data)

    async def list(
        self,
        *,
        user_id: str | None = None,
        status: str = "active",
        type: MemoryType | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Memory]:
        """List user memories asynchronously."""
        params: dict[str, Any] = {
            "status": status,
            "limit": limit,
            "offset": offset,
        }
        uid = user_id or self.user_id
        if uid:
            params["user_id"] = uid
        if type:
            params["type"] = type

        data = await self._request("GET", "/memories", params=params)
        return [Memory.model_validate(item) for item in data]

    async def update(
        self,
        memory_id: str | UUID,
        *,
        content: str | None = None,
        type: MemoryType | None = None,
        importance: float | None = None,
        user_id: str | None = None,
    ) -> Memory:
        """Update an existing memory asynchronously."""
        payload: dict[str, Any] = {}
        if content is not None:
            payload["content"] = content
        if type is not None:
            payload["type"] = type
        if importance is not None:
            payload["importance"] = importance

        params: dict[str, Any] = {}
        uid = user_id or self.user_id
        if uid:
            params["user_id"] = uid

        data = await self._request("PATCH", f"/memories/{memory_id}", json=payload, params=params)
        return Memory.model_validate(data)
