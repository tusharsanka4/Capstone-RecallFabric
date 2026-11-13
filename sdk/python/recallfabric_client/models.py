"""Pydantic data models for RecallFabric Client SDK."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

MemoryType = Literal["preference", "goal", "skill", "profile", "fact", "other"]


class Memory(BaseModel):
    """Memory record representation."""

    model_config = ConfigDict(extra="ignore")

    id: UUID
    user_id: str
    content: str
    type: MemoryType = "fact"
    importance: float = 0.5
    confidence: float = 1.0
    source: str = "direct"
    version: int = 1
    previous_version: int | None = None
    status: str = "active"
    creation_reason: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)
    embedding_model: str | None = None
    embedding_dimensions: int | None = None


class RememberResult(BaseModel):
    """Response returned from client.remember()."""

    model_config = ConfigDict(extra="ignore")

    status: str
    action: str = "created"
    memory: Memory | None = None
    memories: list[Memory] = Field(default_factory=list)
    count: int = 1
    message: str = ""


class RecallItem(BaseModel):
    """A scored memory item returned inside client.recall()."""

    model_config = ConfigDict(extra="ignore")

    id: UUID
    user_id: str
    content: str
    type: MemoryType = "fact"
    importance: float = 0.5
    confidence: float = 1.0
    source: str = "direct"
    version: int = 1
    score: float = 0.0
    similarity: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class RecallResult(BaseModel):
    """Response returned from client.recall()."""

    model_config = ConfigDict(extra="ignore")

    context: str
    memories: list[RecallItem] = Field(default_factory=list)
    count: int = 0
    query: str = ""


class ForgetResult(BaseModel):
    """Response returned from client.forget()."""

    model_config = ConfigDict(extra="ignore")

    confirmed: bool = False
    status: str = "pending_confirmation"
    deleted_id: str | None = None
    candidate: Memory | None = None
    deleted_memory: Memory | None = None
    message: str = ""


class ProfileResult(BaseModel):
    """Response returned from client.profile()."""

    model_config = ConfigDict(extra="ignore")

    user_id: str
    summary: str
    memory_count: int = 0
    categories: dict[str, list[str]] = Field(default_factory=dict)
    memories: list[Memory] = Field(default_factory=list)


class CapabilitiesResult(BaseModel):
    """Response returned from client.capabilities()."""

    model_config = ConfigDict(extra="ignore")

    service: str = "recallfabric"
    service_version: str = "0.1.0"
    api_version: str = "v1"
    supported_memory_types: list[str] = Field(default_factory=list)
    embedding_model: str = ""
    embedding_dimensions: int = 0
    enabled_features: dict[str, bool] = Field(default_factory=dict)
    limits: dict[str, Any] = Field(default_factory=dict)
