from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from recallfabric.db.models import ApiKey, Memory, MemoryEvent
from recallfabric.db.session import get_session
from recallfabric.memory_manager.events import (
    get_memory_provenance_records,
    to_event_read,
)
from recallfabric.schemas.provenance import (
    MemoryProvenanceResponse,
    ProvenanceFeedPage,
)
from recallfabric.security.auth import get_current_api_key, verify_user_access

router = APIRouter(prefix="/provenance", tags=["provenance"])
Database = Annotated[Session, Depends(get_session)]
Owner = Annotated[str, Query(min_length=1, max_length=255, pattern=r"\S")]
ApiKeyDep = Annotated[ApiKey | None, Depends(get_current_api_key)]


@router.get("", response_model=ProvenanceFeedPage)
def list_provenance_feed(
    user_id: Owner,
    session: Database,
    request: Request,
    api_key: ApiKeyDep = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
    event_type: str | None = None,
    memory_id: UUID | None = None,
    order: Literal["asc", "desc"] = "asc",
):
    verify_user_access(user_id, api_key, request.app.state.settings)
    with session.begin():
        stmt = select(MemoryEvent).where(MemoryEvent.user_id == user_id)
        if event_type is not None:
            stmt = stmt.where(MemoryEvent.event_type == event_type)
        if memory_id is not None:
            stmt = stmt.where(MemoryEvent.memory_id == memory_id)
        if order == "desc":
            stmt = stmt.order_by(MemoryEvent.created_at.desc(), MemoryEvent.id.desc())
        else:
            stmt = stmt.order_by(MemoryEvent.created_at.asc(), MemoryEvent.id.asc())

        events = session.execute(stmt.offset(offset).limit(limit + 1)).scalars().all()
        has_more = len(events) > limit
        page_events = events[:limit]

        mem_ids = {e.memory_id for e in page_events}
        rev_map = {}
        if mem_ids:
            revisions = (
                session.execute(
                    select(Memory).where(Memory.id.in_(mem_ids), Memory.user_id == user_id)
                )
                .scalars()
                .all()
            )
            rev_map = {(r.id, r.version): r for r in revisions}

        reads = [
            to_event_read(e, rev_map.get((e.memory_id, e.memory_version))) for e in page_events
        ]
        return ProvenanceFeedPage(
            items=reads,
            events=reads,
            limit=limit,
            offset=offset,
            has_more=has_more,
        )


@router.get("/{memory_id}", response_model=MemoryProvenanceResponse)
def get_memory_provenance_route(
    memory_id: UUID,
    user_id: Owner,
    session: Database,
    request: Request,
    api_key: ApiKeyDep = None,
):
    verify_user_access(user_id, api_key, request.app.state.settings)
    with session.begin():
        return get_memory_provenance_records(session, user_id, memory_id)
