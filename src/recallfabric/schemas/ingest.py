"""Schemas for asynchronous webhook transcript ingestion."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class IngestMessage(BaseModel):
    role: str
    content: str


class IngestRequest(BaseModel):
    user_id: str | None = None
    transcript: list[IngestMessage] | list[dict[str, Any]] = Field(
        ..., min_length=1, description="List of conversation turns to extract memories from"
    )
    source: str = Field(default="webhook_ingest", description="Source identifier")
    metadata: dict[str, Any] = Field(default_factory=dict)


class IngestJobResponse(BaseModel):
    job_id: str
    status: str = "pending"
    message: str
    status_url: str


class IngestJobStatus(BaseModel):
    job_id: str
    user_id: str
    status: str = Field(..., description="'pending', 'processing', 'completed', or 'failed'")
    message_count: int
    extracted_count: int = 0
    memories: list[dict[str, Any]] = Field(default_factory=list)
    error: str | None = None
    created_at: str
    updated_at: str | None = None
