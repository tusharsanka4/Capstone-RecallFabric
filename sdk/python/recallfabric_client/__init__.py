from recallfabric_client.adapters.langchain import (
    RecallFabricMemory,
    RecallFabricRetriever,
)
from recallfabric_client.adapters.llamaindex import (
    RecallFabricLlamaIndexRetriever,
)
from recallfabric_client.client import AsyncRecallFabric, RecallFabric
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
    ProfileResult,
    RecallItem,
    RecallResult,
    RememberResult,
)
from recallfabric_client.wrapper import async_with_memory, with_memory

__version__ = "0.1.0"

__all__ = [
    "RecallFabric",
    "AsyncRecallFabric",
    "with_memory",
    "async_with_memory",
    # Adapters
    "RecallFabricRetriever",
    "RecallFabricMemory",
    "RecallFabricLlamaIndexRetriever",
    # Models
    "Memory",
    "RememberResult",
    "RecallResult",
    "RecallItem",
    "ForgetResult",
    "ProfileResult",
    "CapabilitiesResult",
    # Exceptions
    "RecallFabricError",
    "APIError",
    "AuthenticationError",
    "PermissionDeniedError",
    "NotFoundError",
    "RateLimitError",
    "TimeoutError",
    "ConnectionError",
]
