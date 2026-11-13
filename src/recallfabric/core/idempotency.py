"""Thread-safe idempotency key store for preventing duplicate operations."""

from __future__ import annotations

import threading
import time
from typing import Any


class IdempotencyRecord:
    def __init__(
        self,
        status_code: int,
        content: Any,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status_code = status_code
        self.content = content
        self.headers = headers or {}
        self.created_at = time.time()


class IdempotencyStore:
    def __init__(self, ttl_seconds: float = 86400.0) -> None:
        self._lock = threading.Lock()
        self._store: dict[str, IdempotencyRecord] = {}
        self._ttl_seconds = ttl_seconds

    def _make_key(self, user_id: str, idempotency_key: str) -> str:
        return f"{user_id}:{idempotency_key.strip()}"

    def get(self, user_id: str, idempotency_key: str) -> IdempotencyRecord | None:
        key = self._make_key(user_id, idempotency_key)
        now = time.time()
        with self._lock:
            record = self._store.get(key)
            if record is None:
                return None
            if now - record.created_at > self._ttl_seconds:
                del self._store[key]
                return None
            return record

    def set(
        self,
        user_id: str,
        idempotency_key: str,
        status_code: int,
        content: Any,
        headers: dict[str, str] | None = None,
    ) -> None:
        key = self._make_key(user_id, idempotency_key)
        record = IdempotencyRecord(status_code=status_code, content=content, headers=headers)
        with self._lock:
            self._store[key] = record

    def clear(self) -> None:
        with self._lock:
            self._store.clear()


# Global in-memory idempotency instance
default_idempotency_store = IdempotencyStore()
