"""Memory input and output contracts."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, StringConstraints

MemoryType = Literal["preference", "goal", "skill", "profile", "fact", "other"]
MemoryStatus = Literal["active", "disabled", "superseded"]
NonemptyText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Score = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]


class MemoryFields(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: NonemptyText
    type: MemoryType
    importance: Score = 0.5
    confidence: Score = 1.0
    source: Annotated[NonemptyText, Field(max_length=512)]
    creation_reason: NonemptyText | None = None
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class MemoryCreate(MemoryFields):
    user_id: Annotated[NonemptyText, Field(max_length=255)]
    deduplicate: bool = False


class MemoryUpdate(MemoryFields):
    expected_version: int = Field(ge=1)
    status: Literal["active", "disabled"] = "active"


class MemorySearch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: Annotated[NonemptyText, Field(max_length=255)]
    query: Annotated[NonemptyText, Field(max_length=1000)]
    type: MemoryType | None = None
    status: Literal["active", "disabled"] = "active"
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class MemoryRead(MemoryFields):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True, extra="forbid")

    id: UUID
    user_id: Annotated[NonemptyText, Field(max_length=255)]
    version: int = Field(ge=1)
    previous_version: int | None = Field(default=None, ge=1)
    status: MemoryStatus
    metadata: dict[str, JsonValue] = Field(default_factory=dict, validation_alias="attributes")
    embedding_model: str | None = None
    embedding_dimensions: int | None = None
    created_at: datetime
    updated_at: datetime
    last_accessed_at: datetime | None = None
    access_count: int = Field(ge=0)
    action: Literal["created", "consolidated", "ignored"] | None = None
    matched_memory_id: UUID | None = None
    conflict_resolution: dict[str, JsonValue] | None = None


class MemoryPage(BaseModel):
    items: list[MemoryRead]
    limit: int
    offset: int
    has_more: bool


class MemoryRetrieve(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: Annotated[NonemptyText, Field(max_length=255)]
    query: Annotated[NonemptyText, Field(max_length=1000)]
    type: MemoryType | None = None
    status: Literal["active", "disabled"] = "active"
    limit: int = Field(default=20, ge=1, le=100)
    min_score: float | None = Field(default=None, ge=-1.0, le=1.0)
    track_access: bool = True


class ScoreBreakdown(BaseModel):
    model_config = ConfigDict(extra="forbid")

    relevance: float
    importance: float
    confidence: float
    recency: float
    frequency: float


class MemoryRanked(MemoryRead):
    score: float
    score_breakdown: ScoreBreakdown | None = None


class MemoryRankedPage(BaseModel):
    items: list[MemoryRanked]
    limit: int
    has_more: bool
