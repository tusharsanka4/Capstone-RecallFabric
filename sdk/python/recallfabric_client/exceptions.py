"""Custom exceptions for RecallFabric Client SDK."""

from __future__ import annotations

from typing import Any


class RecallFabricError(Exception):
    """Base exception for all RecallFabric SDK errors."""


class APIError(RecallFabricError):
    """Raised when the RecallFabric API returns an error response."""

    def __init__(
        self,
        status_code: int,
        message: str,
        code: str = "API_ERROR",
        details: Any = None,
    ) -> None:
        super().__init__(f"[{code}] {message} (HTTP {status_code})")
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details


class AuthenticationError(APIError):
    """Raised when authentication fails (HTTP 401)."""

    def __init__(self, message: str = "Invalid or missing API key.", details: Any = None) -> None:
        super().__init__(
            status_code=401,
            message=message,
            code="AUTHENTICATION_ERROR",
            details=details,
        )


class PermissionDeniedError(APIError):
    """Raised when access is forbidden (HTTP 403)."""

    def __init__(
        self,
        message: str = "Access forbidden.",
        details: Any = None,
    ) -> None:
        super().__init__(
            status_code=403,
            message=message,
            code="PERMISSION_DENIED",
            details=details,
        )


class NotFoundError(APIError):
    """Raised when a requested resource is not found (HTTP 404)."""

    def __init__(
        self,
        message: str = "Resource not found.",
        details: Any = None,
    ) -> None:
        super().__init__(
            status_code=404,
            message=message,
            code="NOT_FOUND",
            details=details,
        )


class RateLimitError(APIError):
    """Raised when request rate limit is exceeded (HTTP 429)."""

    def __init__(
        self,
        message: str = "Rate limit exceeded. Please back off.",
        details: Any = None,
    ) -> None:
        super().__init__(
            status_code=429,
            message=message,
            code="RATE_LIMIT_EXCEEDED",
            details=details,
        )


class TimeoutError(RecallFabricError):
    """Raised when an API request times out."""


class ConnectionError(RecallFabricError):
    """Raised when unable to establish connection to the RecallFabric service."""
