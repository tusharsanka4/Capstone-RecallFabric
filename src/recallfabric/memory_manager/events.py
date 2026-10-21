from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from recallfabric.db.models import Memory, MemoryEvent
from recallfabric.schemas.provenance import MemoryEventRead, MemoryProvenanceResponse


def record_event(
    session: Session,
    user_id: str,
    memory_id: UUID,
    event_type: str,
    memory_version: int | None = None,
    reason: str | None = None,
    source: str | None = None,
    actor: str = "user",
    detail: dict[str, Any] | None = None,
) -> MemoryEvent:
    event = MemoryEvent(
        user_id=user_id,
        memory_id=memory_id,
        memory_version=memory_version,
        event_type=event_type,
        reason=reason,
        source=source,
        actor=actor,
        detail=detail or {},
    )
    session.add(event)
    return event


def to_event_read(
    event: MemoryEvent,
    revision: Memory | None = None,
) -> MemoryEventRead:
    conf = None
    if event.detail and isinstance(event.detail, dict):
        conf = event.detail.get("confidence")
    if conf is None and revision is not None:
        conf = revision.confidence

    src = event.source
    if not src and revision is not None:
        src = revision.source

    reason = event.reason
    if not reason and revision is not None:
        reason = revision.creation_reason

    return MemoryEventRead(
        id=event.id,
        memory_id=event.memory_id,
        memory_version=event.memory_version,
        user_id=event.user_id,
        event_type=event.event_type,
        reason=reason,
        creation_reason=reason,
        source=src,
        actor=event.actor,
        confidence=float(conf) if conf is not None else None,
        detail=event.detail or {},
        created_at=event.created_at,
    )


def get_memory_provenance_records(
    session: Session,
    user_id: str,
    memory_id: UUID,
) -> MemoryProvenanceResponse:
    events = (
        session.execute(
            select(MemoryEvent)
            .where(MemoryEvent.memory_id == memory_id, MemoryEvent.user_id == user_id)
            .order_by(MemoryEvent.created_at.asc(), MemoryEvent.id.asc())
        )
        .scalars()
        .all()
    )
    revisions = (
        session.execute(select(Memory).where(Memory.id == memory_id, Memory.user_id == user_id))
        .scalars()
        .all()
    )
    if not events and not revisions:
        raise HTTPException(404, "Memory not found")
    rev_map = {r.version: r for r in revisions}
    event_reads = [to_event_read(e, rev_map.get(e.memory_version)) for e in events]
    return MemoryProvenanceResponse(events=event_reads, items=event_reads)
