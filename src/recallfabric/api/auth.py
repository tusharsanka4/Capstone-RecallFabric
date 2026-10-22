from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from recallfabric.core.config import Settings, get_settings
from recallfabric.db.models import ApiKey
from recallfabric.db.session import get_session
from recallfabric.schemas.auth import (
    ApiKeyCreatedResponse,
    ApiKeyInfoResponse,
    CreateApiKeyRequest,
    SignupRequest,
    SignupResponse,
)
from recallfabric.security.audit import record_audit_event
from recallfabric.security.auth import generate_api_key, require_admin_token

router = APIRouter(prefix="/auth", tags=["auth"])
SessionDep = Annotated[Session, Depends(get_session)]
AdminDep = Annotated[str, Depends(require_admin_token)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


@router.post(
    "/keys",
    response_model=ApiKeyCreatedResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="create_api_key",
)
def create_api_key(
    payload: CreateApiKeyRequest,
    request: Request,
    db: SessionDep,
    _admin: AdminDep,
) -> ApiKeyCreatedResponse:
    raw_key, key_hash = generate_api_key()
    key_record = ApiKey(
        id=uuid4(),
        user_id=payload.user_id,
        name=payload.name,
        key_hash=key_hash,
    )
    db.add(key_record)
    db.commit()
    db.refresh(key_record)

    record_audit_event(
        db,
        "key_created",
        user_id=payload.user_id,
        ip_address=request.client.host if request.client else None,
        detail={"key_id": str(key_record.id), "name": payload.name},
    )
    db.commit()

    return ApiKeyCreatedResponse(
        id=key_record.id,
        user_id=key_record.user_id,
        name=key_record.name,
        key=raw_key,
        created_at=key_record.created_at,
    )


@router.post(
    "/signup",
    response_model=SignupResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="signup_user",
    summary="Self-serve onboarding for new users",
    description="Registers a user and issues an active API key when public signup is enabled.",
)
def signup(
    payload: SignupRequest,
    request: Request,
    db: SessionDep,
    settings: SettingsDep,
) -> SignupResponse:
    if settings.auth_enabled and not settings.allow_public_signup:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Public signup is currently disabled. Contact your administrator.",
        )

    raw_key, key_hash = generate_api_key()
    key_record = ApiKey(
        id=uuid4(),
        user_id=payload.user_id,
        name=payload.name or "default",
        key_hash=key_hash,
    )
    db.add(key_record)
    db.commit()
    db.refresh(key_record)

    record_audit_event(
        db,
        "user_signup",
        user_id=payload.user_id,
        ip_address=request.client.host if request.client else None,
        detail={"key_id": str(key_record.id), "name": key_record.name},
    )
    db.commit()

    return SignupResponse(
        user_id=payload.user_id,
        api_key=raw_key,
        name=key_record.name,
        message="User onboarded successfully. Keep this API key safe.",
    )


@router.get("/keys", response_model=list[ApiKeyInfoResponse], operation_id="list_api_keys")
def list_api_keys(
    db: SessionDep,
    _admin: AdminDep,
    user_id: str | None = Query(default=None),
) -> list[ApiKeyInfoResponse]:
    stmt = select(ApiKey).order_by(ApiKey.created_at.desc())
    if user_id:
        stmt = stmt.where(ApiKey.user_id == user_id)
    records = db.scalars(stmt).all()
    return [
        ApiKeyInfoResponse(
            id=r.id,
            user_id=r.user_id,
            name=r.name,
            created_at=r.created_at,
            last_used_at=r.last_used_at,
            revoked_at=r.revoked_at,
        )
        for r in records
    ]


@router.delete(
    "/keys/{key_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="revoke_api_key",
)
def revoke_api_key(
    key_id: UUID,
    request: Request,
    db: SessionDep,
    _admin: AdminDep,
) -> None:
    key_record = db.get(ApiKey, key_id)
    if key_record is None:
        raise HTTPException(status_code=404, detail="API key not found")

    if key_record.revoked_at is None:
        key_record.revoked_at = datetime.now(UTC)
        record_audit_event(
            db,
            "key_revoked",
            user_id=key_record.user_id,
            ip_address=request.client.host if request.client else None,
            detail={"key_id": str(key_record.id)},
        )
        db.commit()
