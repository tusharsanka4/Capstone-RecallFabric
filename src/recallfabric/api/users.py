from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from recallfabric.core.config import Settings, get_settings
from recallfabric.db.models import ApiKey, Memory, MemoryEvent
from recallfabric.db.session import get_session
from recallfabric.security.audit import record_audit_event
from recallfabric.security.auth import get_current_api_key, verify_user_access
from recallfabric.security.encryption import decrypt_content

router = APIRouter(prefix="/users", tags=["users"])
SessionDep = Annotated[Session, Depends(get_session)]
ApiKeyDep = Annotated[ApiKey | None, Depends(get_current_api_key)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


def resolve_me_user_id(
    query_user_id: str | None,
    api_key: ApiKey | None,
    settings: Settings,
) -> str:
    if settings.auth_enabled:
        if api_key is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required",
            )
        if query_user_id and query_user_id != api_key.user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Forbidden: User ID does not match API key",
            )
        return api_key.user_id

    if not query_user_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="user_id is required when authentication is disabled",
        )
    return query_user_id


@router.delete("/me/memories")
def delete_all_user_memories(
    request: Request,
    db: SessionDep,
    api_key: ApiKeyDep,
    settings: SettingsDep,
    user_id: str | None = Query(default=None),
) -> dict[str, Any]:
    target_user_id = resolve_me_user_id(user_id, api_key, settings)
    verify_user_access(target_user_id, api_key, settings)

    count_stmt = select(func.count()).select_from(Memory).where(Memory.user_id == target_user_id)
    count = db.scalar(count_stmt) or 0

    db.execute(delete(Memory).where(Memory.user_id == target_user_id))
    db.execute(delete(MemoryEvent).where(MemoryEvent.user_id == target_user_id))

    record_audit_event(
        db,
        "bulk_delete",
        user_id=target_user_id,
        ip_address=request.client.host if request.client else None,
        detail={"deleted_memories": count},
    )
    db.commit()

    return {"deleted_memories": count, "user_id": target_user_id}


@router.get("/me/export")
def export_user_data(
    request: Request,
    db: SessionDep,
    api_key: ApiKeyDep,
    settings: SettingsDep,
    user_id: str | None = Query(default=None),
) -> dict[str, Any]:
    target_user_id = resolve_me_user_id(user_id, api_key, settings)
    verify_user_access(target_user_id, api_key, settings)

    encryption_key = settings.encryption_key.get_secret_value() if settings.encryption_key else None

    memories_stmt = (
        select(Memory).where(Memory.user_id == target_user_id).order_by(Memory.id, Memory.version)
    )
    memories = db.scalars(memories_stmt).all()

    events_stmt = (
        select(MemoryEvent)
        .where(MemoryEvent.user_id == target_user_id)
        .order_by(MemoryEvent.created_at)
    )
    events = db.scalars(events_stmt).all()

    exported_memories = [
        {
            "id": str(m.id),
            "version": m.version,
            "previous_version": m.previous_version,
            "user_id": m.user_id,
            "content": decrypt_content(m.content, encryption_key),
            "type": m.type,
            "importance": m.importance,
            "confidence": m.confidence,
            "source": m.source,
            "creation_reason": m.creation_reason,
            "status": m.status,
            "metadata": m.attributes,
            "created_at": m.created_at.isoformat() if m.created_at else None,
            "updated_at": m.updated_at.isoformat() if m.updated_at else None,
            "access_count": m.access_count,
            "last_accessed_at": (m.last_accessed_at.isoformat() if m.last_accessed_at else None),
        }
        for m in memories
    ]

    exported_events = [
        {
            "id": str(e.id),
            "memory_id": str(e.memory_id),
            "memory_version": e.memory_version,
            "user_id": e.user_id,
            "event_type": e.event_type,
            "reason": e.reason,
            "source": e.source,
            "actor": e.actor,
            "detail": e.detail,
            "created_at": e.created_at.isoformat() if e.created_at else None,
        }
        for e in events
    ]

    record_audit_event(
        db,
        "export",
        user_id=target_user_id,
        ip_address=request.client.host if request.client else None,
        detail={"memories_count": len(exported_memories), "events_count": len(exported_events)},
    )
    db.commit()

    return {
        "user_id": target_user_id,
        "memories": exported_memories,
        "events": exported_events,
    }
