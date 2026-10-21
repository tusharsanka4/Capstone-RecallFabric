from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue


class MemoryEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="ignore")

    id: UUID
    memory_id: UUID
    memory_version: int | None = None
    user_id: str
    event_type: str
    reason: str | None = None
    creation_reason: str | None = None
    source: str | None = None
    actor: str | None = None
    confidence: float | None = None
    detail: dict[str, JsonValue] = Field(default_factory=dict)
    created_at: datetime


class MemoryProvenanceResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    events: list[MemoryEventRead]
    items: list[MemoryEventRead]


class ProvenanceFeedPage(BaseModel):
    model_config = ConfigDict(extra="ignore")

    items: list[MemoryEventRead]
    events: list[MemoryEventRead]
    limit: int
    offset: int
    has_more: bool
