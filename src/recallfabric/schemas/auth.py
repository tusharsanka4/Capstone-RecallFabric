from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class CreateApiKeyRequest(BaseModel):
    user_id: str = Field(min_length=1, max_length=255)
    name: str = Field(min_length=1, max_length=255)


class ApiKeyCreatedResponse(BaseModel):
    id: UUID
    user_id: str
    name: str
    key: str
    created_at: datetime


class ApiKeyInfoResponse(BaseModel):
    id: UUID
    user_id: str
    name: str
    created_at: datetime
    last_used_at: datetime | None = None
    revoked_at: datetime | None = None
