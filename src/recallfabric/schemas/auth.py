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


class SignupRequest(BaseModel):
    user_id: str = Field(min_length=1, max_length=255, description="Desired unique user identifier")
    name: str | None = Field(
        default="default", max_length=255, description="Optional key description"
    )


class SignupResponse(BaseModel):
    user_id: str
    api_key: str
    name: str
    message: str
