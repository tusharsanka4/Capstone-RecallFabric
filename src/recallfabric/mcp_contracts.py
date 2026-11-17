"""Bounded tool inputs and sanitized MCP errors shared by all exposed tools."""

from functools import wraps
from typing import Annotated

from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field, StringConstraints, ValidationError
from sqlalchemy.exc import IntegrityError, OperationalError, SQLAlchemyError, TimeoutError

from recallfabric.embeddings.service import EmbeddingUnavailable
from recallfabric.providers.base import ProviderError
from recallfabric.services.locking import MemoryConflict, MemoryNotFound

MemoryText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20000)
]
QueryText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]
ResultLimit = Annotated[int, Field(ge=1, le=100)]
Revision = Annotated[int, Field(ge=1)]


def tool_errors(function):
    """Preserve signatures for discovery and keep provider/SQL details out of results."""

    @wraps(function)
    def wrapped(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except ToolError:
            raise
        except PermissionError:
            raise ToolError(
                "FORBIDDEN: Credentials or scopes do not allow this operation"
            ) from None
        except MemoryNotFound:
            raise ToolError("NOT_FOUND: Memory not found") from None
        except (MemoryConflict, IntegrityError):
            raise ToolError(
                "CONFLICT: Memory changed; reload its current version and retry"
            ) from None
        except EmbeddingUnavailable:
            raise ToolError("EMBEDDING_UNAVAILABLE: Check the configured embedding model") from None
        except ProviderError:
            raise ToolError(
                "PROVIDER_UNAVAILABLE: Extraction failed; no memories were stored"
            ) from None
        except (OperationalError, TimeoutError):
            raise ToolError(
                "DATABASE_UNAVAILABLE: Try again when the database is available"
            ) from None
        except SQLAlchemyError:
            raise ToolError("DATABASE_ERROR: The operation could not be completed") from None
        except (ValueError, ValidationError):
            raise ToolError(
                "INVALID_ARGUMENT: Check the supplied values and required version"
            ) from None
        except Exception:
            raise ToolError("INTERNAL_ERROR: The operation could not be completed") from None

    return wrapped
