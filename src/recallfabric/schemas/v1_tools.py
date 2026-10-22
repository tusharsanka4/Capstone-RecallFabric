"""Schemas for task-oriented AI tool endpoints, capabilities, and consistent v1 error format."""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from recallfabric.schemas.memory import MemoryRead, MemoryType, Score


class ErrorDetail(BaseModel):
    """Detailed error representation for the /v1 API surface."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "code": "NOT_FOUND",
                    "message": "Memory 9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d not found.",
                }
            ]
        },
    )

    code: str = Field(
        description="Machine-readable error code (e.g. VALIDATION_ERROR, NOT_FOUND, UNAUTHORIZED)",
        examples=["NOT_FOUND"],
    )
    message: str = Field(
        description="Human-readable and LLM-actionable explanation of the error",
        examples=["Memory not found."],
    )


class ErrorResponse(BaseModel):
    """Consistent error envelope returned by all /v1 endpoints on failure."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "error": {
                        "code": "VALIDATION_ERROR",
                        "message": "Either 'content' or 'text' must be provided and non-empty.",
                    }
                }
            ]
        },
    )

    error: ErrorDetail


class CapabilitiesResponse(BaseModel):
    """Service capabilities, supported categories, active model, and operational limits."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "service_version": "0.1.0",
                    "supported_memory_types": [
                        "preference",
                        "goal",
                        "skill",
                        "profile",
                        "fact",
                        "other",
                    ],
                    "embedding_model": "BAAI/bge-small-en-v1.5",
                    "embedding_dimensions": 384,
                    "enabled_features": {
                        "auth": True,
                        "encryption": False,
                        "rate_limiting": True,
                        "provenance": True,
                        "hybrid_ranking": True,
                        "deduplication": True,
                        "conflict_resolution": True,
                    },
                    "limits": {
                        "rate_limit_rps": 20.0,
                        "rate_limit_burst": 40,
                        "max_request_size_bytes": 1048576,
                        "context_max_chars": 2000,
                    },
                }
            ]
        },
    )

    service_version: str = Field(
        description="Semantic version of the RecallFabric service",
        examples=["0.1.0"],
    )
    supported_memory_types: list[str] = Field(
        description="Supported memory classification categories",
        examples=[["preference", "goal", "skill", "profile", "fact", "other"]],
    )
    embedding_model: str = Field(
        description="Active embedding model identifier used for semantic search and ranking",
        examples=["BAAI/bge-small-en-v1.5"],
    )
    embedding_dimensions: int = Field(
        description="Vector dimensionality of the active embedding model",
        examples=[384],
    )
    enabled_features: dict[str, bool] = Field(
        description="Status of operational features and security capabilities",
        examples=[
            {
                "auth": True,
                "encryption": False,
                "rate_limiting": True,
                "provenance": True,
                "hybrid_ranking": True,
                "deduplication": True,
                "conflict_resolution": True,
            }
        ],
    )
    limits: dict[str, Any] = Field(
        description="Operational limits, rate limiting thresholds, and context character budgets",
        examples=[
            {
                "rate_limit_rps": 20.0,
                "rate_limit_burst": 40,
                "max_request_size_bytes": 1048576,
                "context_max_chars": 2000,
            }
        ],
    )


class RememberRequest(BaseModel):
    """Store explicit memory or extract facts from free-form conversation text.

    Designed for AI tool use: pass `content` for direct storage or `text` with `extract=true`
    to isolate atomic facts automatically.
    """

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "content": "User prefers concise Python code snippets.",
                    "type": "preference",
                    "importance": 0.8,
                    "confidence": 1.0,
                    "source": "chat_session_42",
                    "extract": False,
                },
                {
                    "text": "I just moved to Seattle and I work as a systems engineer.",
                    "source": "user_onboarding",
                    "extract": True,
                },
            ]
        },
    )

    content: str | None = Field(
        default=None,
        description="Direct memory statement to store. 'content' or 'text' must be provided.",
        examples=["User prefers concise Python code snippets."],
    )
    text: str | None = Field(
        default=None,
        description=(
            "Free text or conversation turn from which to extract memories when extract=true, "
            "or alias for content."
        ),
        examples=["I just moved to Seattle and I work as a systems engineer."],
    )
    type: MemoryType = Field(
        default="fact",
        description="Category of the memory: preference, goal, skill, profile, fact, or other",
        examples=["preference"],
    )
    importance: Score | None = Field(
        default=None,
        description=(
            "Importance score from 0.0 to 1.0. Defaults to 0.5 (or model-assessed "
            "when extract=true)."
        ),
        examples=[0.8],
    )
    confidence: Score = Field(
        default=1.0,
        description="Confidence score from 0.0 to 1.0 that this memory is accurate and truthful.",
        examples=[1.0],
    )
    source: str = Field(
        default="ai_agent",
        max_length=512,
        description="Source identifier (e.g. system name, conversation ID, tool call).",
        examples=["ai_agent"],
    )
    extract: bool = Field(
        default=False,
        description=(
            "When true, passes text through the LLM extraction pipeline to isolate atomic facts."
        ),
        examples=[False],
    )
    user_id: str | None = Field(
        default=None,
        description=(
            "Target user identifier (optional; automatically derived from authenticated API key "
            "when auth is enabled)."
        ),
        examples=["user_123"],
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary JSON metadata attributes to attach to the memory.",
        examples=[{"topic": "coding_style"}],
    )


class RememberResponse(BaseModel):
    """Result of the remember tool operation."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "status": "created",
                    "action": "created",
                    "memory": None,
                    "memories": [],
                    "count": 1,
                    "message": "Memory created successfully.",
                }
            ]
        },
    )

    status: Literal["created", "deduplicated", "superseded", "extracted"] = Field(
        description=(
            "Outcome category: created (new), deduplicated (existing updated), "
            "superseded (conflicting replaced), or extracted."
        ),
        examples=["created"],
    )
    action: str = Field(
        description="Specific action performed by the memory manager",
        examples=["created"],
    )
    memory: MemoryRead | None = Field(
        default=None,
        description="The primary stored or matched memory record (for single memory operations)",
    )
    memories: list[MemoryRead] = Field(
        default_factory=list,
        description="List of memories stored or extracted during this operation",
    )
    count: int = Field(
        default=1,
        description="Number of memories affected by this operation",
        examples=[1],
    )
    message: str = Field(
        description="Human and LLM-readable summary of the operation outcome",
        examples=["Memory created successfully."],
    )


class RecallRequest(BaseModel):
    """Search and retrieve user memories ranked by semantic relevance and recency."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "query": "What are the user's favorite programming languages?",
                    "limit": 5,
                    "type": "preference",
                }
            ]
        },
    )

    query: str = Field(
        min_length=1,
        max_length=2000,
        description="Natural language query or question describing memories to retrieve.",
        examples=["What are the user's favorite programming languages and editor preferences?"],
    )
    limit: int = Field(
        default=5,
        ge=1,
        le=50,
        description="Maximum number of memory items to return.",
        examples=[5],
    )
    type: MemoryType | None = Field(
        default=None,
        description="Optional filter: preference, goal, skill, profile, fact, or other.",
        examples=["preference"],
    )
    user_id: str | None = Field(
        default=None,
        description=(
            "Target user identifier (optional; automatically derived from authenticated API key "
            "when auth is enabled)."
        ),
        examples=["user_123"],
    )
    min_similarity: float | None = Field(
        default=None,
        ge=-1.0,
        le=1.0,
        description="Minimum cosine cutoff (defaults to service retrieval_min_similarity).",
        examples=[0.4],
    )


class RecallMemoryItem(BaseModel):
    """A single memory returned by recall with relevance and scoring details."""

    id: UUID
    user_id: str
    content: str
    type: MemoryType
    importance: float
    confidence: float
    source: str
    version: int
    score: float = Field(
        description="Combined ranking score (relevance, importance, recency, etc.)"
    )
    similarity: float | None = Field(default=None, description="Pure semantic cosine similarity")
    metadata: dict[str, Any] = Field(default_factory=dict)


class RecallResponse(BaseModel):
    """Ranked memories and pre-assembled context string ready for LLM prompt injection."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "context": "- [preference] User prefers dark mode\n- [skill] Python expert",
                    "memories": [],
                    "count": 2,
                    "query": "coding preferences",
                }
            ]
        },
    )

    context: str = Field(
        description=(
            "Formatted markdown context block containing top relevant memories, budgeted to fit "
            "system prompt limits."
        ),
        examples=["- [preference] User prefers dark mode\n- [skill] Python expert"],
    )
    memories: list[RecallMemoryItem] = Field(
        default_factory=list,
        description="List of retrieved memories with score breakdown, content, and metadata.",
    )
    count: int = Field(
        description="Total number of memories retrieved.",
        examples=[2],
    )
    query: str = Field(
        description="The query that was executed.",
        examples=["coding preferences"],
    )


class ForgetRequest(BaseModel):
    """Delete a memory by ID or search for it semantically with confirmation."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "query": "User dislikes spicy food",
                    "confirm": False,
                },
                {
                    "memory_id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
                    "confirm": True,
                },
            ]
        },
    )

    memory_id: UUID | None = Field(
        default=None,
        description="Exact UUID of the memory to forget/delete.",
        examples=["9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d"],
    )
    query: str | None = Field(
        default=None,
        description="Semantic search query to find the memory to delete if memory_id is unknown.",
        examples=["User dislikes spicy food"],
    )
    confirm: bool = Field(
        default=False,
        description=(
            "Confirmation flag. When false and using query, returns candidate memory without "
            "deleting. When true, permanently deletes it."
        ),
        examples=[False],
    )
    user_id: str | None = Field(
        default=None,
        description=(
            "Target user identifier (optional; automatically derived from authenticated API key "
            "when auth is enabled)."
        ),
        examples=["user_123"],
    )


class ForgetResponse(BaseModel):
    """Result of the forget tool operation."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "confirmed": True,
                    "status": "deleted",
                    "deleted_id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
                    "candidate": None,
                    "deleted_memory": None,
                    "message": "Memory 9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d deleted successfully.",
                }
            ]
        },
    )

    confirmed: bool = Field(
        description=(
            "True if memory was permanently deleted; False if confirmation is required "
            "or memory not found."
        ),
        examples=[True],
    )
    status: Literal["deleted", "pending_confirmation", "not_found"] = Field(
        description="Status of the forget request.",
        examples=["deleted"],
    )
    deleted_id: str | None = Field(
        default=None,
        description="ID of the deleted memory if deletion occurred.",
        examples=["9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d"],
    )
    candidate: MemoryRead | None = Field(
        default=None,
        description=(
            "Candidate memory found by semantic search awaiting confirmation when confirm=false."
        ),
    )
    deleted_memory: MemoryRead | None = Field(
        default=None,
        description="The memory record that was deleted.",
    )
    message: str = Field(
        description=(
            "Human and LLM-readable message explaining the result or prompting for confirmation."
        ),
        examples=["Memory deleted successfully."],
    )


class ProfileResponse(BaseModel):
    """Compact summary of the most important active memories for the user."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "user_id": "user_123",
                    "summary": "User Profile Summary:\n- [profile] Engineer\n- [preference] Python",
                    "memory_count": 2,
                    "categories": {
                        "profile": ["Engineer"],
                        "preference": ["Python"],
                    },
                    "memories": [],
                }
            ]
        },
    )

    user_id: str = Field(
        description="The user ID for this profile",
        examples=["user_123"],
    )
    summary: str = Field(
        description="Formatted markdown profile summary ready for LLM context injection",
        examples=["User Profile Summary:\n- [profile] Engineer\n- [preference] Python"],
    )
    memory_count: int = Field(
        description="Total number of active memories included in the profile",
        examples=[2],
    )
    categories: dict[str, list[str]] = Field(
        description="Active memory contents grouped by category",
        examples=[
            {
                "profile": ["Senior Software Engineer"],
                "preference": ["Prefers Python"],
            }
        ],
    )
    memories: list[MemoryRead] = Field(
        default_factory=list,
        description="Top active memories ranked by importance and recency",
    )
