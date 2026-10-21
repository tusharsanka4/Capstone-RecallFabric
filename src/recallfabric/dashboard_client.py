import os
from typing import Any

import httpx


class DashboardClientError(Exception):
    def __init__(self, status_code: int, detail: str, response: httpx.Response | None = None):
        super().__init__(f"HTTP {status_code}: {detail}")
        self.status_code = status_code
        self.detail = detail
        self.response = response


def _get_client(
    client: httpx.Client | None,
    timeout: float = 10.0,
    api_key: str | None = None,
) -> httpx.Client:
    key = api_key or os.environ.get("RECALLFABRIC_API_KEY", "")
    headers = {"X-API-Key": key} if key else {}
    if client is not None:
        if headers:
            client.headers.update(headers)
        return client
    return httpx.Client(timeout=timeout, headers=headers)


def _handle_response(r: httpx.Response) -> httpx.Response:
    if r.status_code >= 400:
        raise DashboardClientError(r.status_code, r.text, r)
    return r


def fetch_memories(
    api_url: str,
    user_id: str,
    limit: int = 50,
    offset: int = 0,
    memory_type: str | None = None,
    status: str | None = None,
    client: httpx.Client | None = None,
) -> list[dict[str, Any]]:
    c = _get_client(client, timeout=10.0)
    params: dict[str, Any] = {"user_id": user_id, "limit": limit, "offset": offset}
    if memory_type:
        params["type"] = memory_type
    if status:
        params["status"] = status
    r = c.get(f"{api_url}/memories", params=params)
    _handle_response(r)
    return r.json().get("items", [])


def create_memory(
    api_url: str,
    user_id: str,
    content: str,
    memory_type: str = "fact",
    importance: float = 0.5,
    confidence: float = 1.0,
    source: str = "dashboard",
    creation_reason: str | None = None,
    deduplicate: bool = False,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    c = _get_client(client, timeout=15.0)
    payload: dict[str, Any] = {
        "user_id": user_id,
        "content": content,
        "type": memory_type,
        "importance": importance,
        "confidence": confidence,
        "source": source,
        "deduplicate": deduplicate,
    }
    if creation_reason:
        payload["creation_reason"] = creation_reason
    r = c.post(f"{api_url}/memories", json=payload)
    _handle_response(r)
    return r.json()


def get_memory(
    api_url: str,
    user_id: str,
    memory_id: str,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    c = _get_client(client, timeout=10.0)
    r = c.get(f"{api_url}/memories/{memory_id}", params={"user_id": user_id})
    _handle_response(r)
    return r.json()


def update_memory(
    api_url: str,
    user_id: str,
    memory_id: str,
    expected_version: int,
    content: str,
    memory_type: str = "fact",
    importance: float = 0.5,
    confidence: float = 1.0,
    source: str = "dashboard",
    creation_reason: str | None = None,
    status: str = "active",
    metadata: dict[str, Any] | None = None,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    c = _get_client(client, timeout=15.0)
    payload: dict[str, Any] = {
        "expected_version": expected_version,
        "content": content,
        "type": memory_type,
        "importance": importance,
        "confidence": confidence,
        "source": source,
        "status": status,
    }
    if creation_reason:
        payload["creation_reason"] = creation_reason
    if metadata:
        payload["metadata"] = metadata
    r = c.put(f"{api_url}/memories/{memory_id}", params={"user_id": user_id}, json=payload)
    _handle_response(r)
    return r.json()


def delete_memory(
    api_url: str,
    user_id: str,
    memory_id: str,
    client: httpx.Client | None = None,
) -> bool:
    c = _get_client(client, timeout=10.0)
    r = c.delete(f"{api_url}/memories/{memory_id}", params={"user_id": user_id})
    _handle_response(r)
    return r.status_code == 204


def disable_memory(
    api_url: str,
    user_id: str,
    memory_id: str,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    c = _get_client(client, timeout=10.0)
    r = c.post(f"{api_url}/memories/{memory_id}/disable", params={"user_id": user_id})
    _handle_response(r)
    return r.json()


def enable_memory(
    api_url: str,
    user_id: str,
    memory_id: str,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    c = _get_client(client, timeout=10.0)
    r = c.post(f"{api_url}/memories/{memory_id}/enable", params={"user_id": user_id})
    _handle_response(r)
    return r.json()


def get_memory_history(
    api_url: str,
    user_id: str,
    memory_id: str,
    limit: int = 20,
    offset: int = 0,
    client: httpx.Client | None = None,
) -> list[dict[str, Any]]:
    c = _get_client(client, timeout=10.0)
    r = c.get(
        f"{api_url}/memories/{memory_id}/versions",
        params={"user_id": user_id, "limit": limit, "offset": offset},
    )
    _handle_response(r)
    return r.json().get("items", [])


def get_memory_provenance(
    api_url: str,
    user_id: str,
    memory_id: str,
    client: httpx.Client | None = None,
) -> list[dict[str, Any]]:
    c = _get_client(client, timeout=10.0)
    r = c.get(
        f"{api_url}/memories/{memory_id}/provenance",
        params={"user_id": user_id},
    )
    _handle_response(r)
    return r.json().get("events", [])


def search_memories(
    api_url: str,
    user_id: str,
    query: str,
    memory_type: str | None = None,
    status: str = "active",
    limit: int = 20,
    offset: int = 0,
    client: httpx.Client | None = None,
) -> list[dict[str, Any]]:
    c = _get_client(client, timeout=10.0)
    payload: dict[str, Any] = {
        "user_id": user_id,
        "query": query,
        "status": status,
        "limit": limit,
        "offset": offset,
    }
    if memory_type:
        payload["type"] = memory_type
    r = c.post(f"{api_url}/memories/search", json=payload)
    _handle_response(r)
    return r.json().get("items", [])


def retrieve_memories(
    api_url: str,
    user_id: str,
    query: str,
    memory_type: str | None = None,
    status: str = "active",
    limit: int = 20,
    min_score: float | None = None,
    track_access: bool = True,
    client: httpx.Client | None = None,
) -> list[dict[str, Any]]:
    c = _get_client(client, timeout=15.0)
    payload: dict[str, Any] = {
        "user_id": user_id,
        "query": query,
        "status": status,
        "limit": limit,
        "track_access": track_access,
    }
    if memory_type:
        payload["type"] = memory_type
    if min_score is not None:
        payload["min_score"] = min_score
    r = c.post(f"{api_url}/memories/retrieve", json=payload)
    _handle_response(r)
    return r.json().get("items", [])


def preview_extraction(
    api_url: str,
    user_id: str,
    text: str,
    source: str = "preview",
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    c = _get_client(client, timeout=60.0)
    payload = {
        "user_id": user_id,
        "text": text,
        "source": source,
        "dry_run": True,
    }
    r = c.post(f"{api_url}/extraction", json=payload)
    _handle_response(r)
    return r.json()


def extract_memories(
    api_url: str,
    user_id: str,
    text: str,
    source: str = "chat_demo",
    client: httpx.Client | None = None,
) -> list[dict[str, Any]]:
    c = _get_client(client, timeout=60.0)
    payload = {
        "user_id": user_id,
        "text": text,
        "source": source,
        "dry_run": False,
    }
    r = c.post(f"{api_url}/extraction", json=payload)
    _handle_response(r)
    return r.json().get("extracted", [])


def chat_with_service(
    api_url: str,
    user_id: str,
    message: str,
    history: list[dict[str, str]],
    extract: bool = True,
    client: httpx.Client | None = None,
) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    c = _get_client(client, timeout=60.0)
    payload = {
        "user_id": user_id,
        "message": message,
        "history": history,
        "extract": extract,
    }
    r = c.post(f"{api_url}/chat", json=payload)
    _handle_response(r)
    data = r.json()
    return data.get("reply", ""), data.get("memories_used", []), data.get("extracted", [])


def clear_all_memories(
    api_url: str,
    user_id: str,
    client: httpx.Client | None = None,
) -> tuple[bool, int | str]:
    deleted = 0
    try:
        mems = fetch_memories(api_url=api_url, user_id=user_id, limit=100, client=client)
        for m in mems:
            if delete_memory(api_url=api_url, user_id=user_id, memory_id=m["id"], client=client):
                deleted += 1
        return True, deleted
    except Exception as e:
        return False, str(e)


def check_status(
    api_url: str,
    ollama_url: str,
    client: httpx.Client | None = None,
) -> tuple[bool, bool]:
    c = _get_client(client, timeout=2.0)
    api_ok, ollama_ok = False, False
    try:
        r = c.get(f"{api_url}/health")
        api_ok = r.status_code == 200
    except Exception:
        pass
    try:
        tags_url = ollama_url.removesuffix("/v1") + "/api/tags"
        r = c.get(tags_url)
        ollama_ok = r.status_code == 200
    except Exception:
        pass
    return api_ok, ollama_ok
