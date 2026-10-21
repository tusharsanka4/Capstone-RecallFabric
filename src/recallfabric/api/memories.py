"""User-scoped memory CRUD and basic text search."""

from datetime import UTC, datetime
from typing import Annotated, Literal
from urllib.parse import urlencode
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from recallfabric.db.models import ApiKey, Memory
from recallfabric.db.session import get_session
from recallfabric.embeddings.service import EmbeddingProvider, get_embedding_provider
from recallfabric.memory_manager.dedupe import acquire_dedupe_lock, deduplicate_and_store
from recallfabric.memory_manager.events import (
    get_memory_provenance_records,
    record_event,
)
from recallfabric.ranking.scoring import (
    calculate_frequency,
    calculate_recency,
    calculate_score,
)
from recallfabric.schemas.memory import (
    MemoryCreate,
    MemoryPage,
    MemoryRanked,
    MemoryRankedPage,
    MemoryRead,
    MemoryRetrieve,
    MemorySearch,
    MemoryType,
    MemoryUpdate,
)
from recallfabric.schemas.provenance import MemoryProvenanceResponse
from recallfabric.security.auth import get_current_api_key, verify_user_access
from recallfabric.security.encryption import decrypt_content, encrypt_content

router = APIRouter(prefix="/memories", tags=["memories"])
Database = Annotated[Session, Depends(get_session)]
Embedder = Annotated[EmbeddingProvider, Depends(get_embedding_provider)]
Owner = Annotated[str, Query(min_length=1, max_length=255, pattern=r"\S")]
CurrentStatus = Literal["active", "disabled"]
ApiKeyDep = Annotated[ApiKey | None, Depends(get_current_api_key)]


def current_query(user_id: str):
    return select(Memory).where(
        Memory.user_id == user_id, Memory.status.in_(["active", "disabled"])
    )


def current_memory(session: Session, user_id: str, memory_id: UUID) -> Memory:
    memory = session.scalar(current_query(user_id).where(Memory.id == memory_id))
    if memory is None:
        raise HTTPException(404, "Memory not found")
    return memory


def lock_memory(session: Session, user_id: str, memory_id: UUID):
    # All writers lock the stable first revision, including after it is superseded.
    root = session.scalar(
        select(Memory)
        .where(Memory.id == memory_id, Memory.user_id == user_id, Memory.version == 1)
        .with_for_update()
    )
    if root is None:
        raise HTTPException(404, "Memory not found")


def to_read_schema(memory: Memory, encryption_key: str | None = None) -> MemoryRead:
    data = MemoryRead.model_validate(memory).model_dump()
    if encryption_key:
        data["content"] = decrypt_content(data["content"], encryption_key)
    return MemoryRead.model_validate(data)


def to_ranked_schema(
    memory: Memory, score: float, breakdown, encryption_key: str | None = None
) -> MemoryRanked:
    data = MemoryRead.model_validate(memory).model_dump()
    if encryption_key:
        data["content"] = decrypt_content(data["content"], encryption_key)
    data["score"] = score
    data["score_breakdown"] = breakdown.model_dump()
    return MemoryRanked.model_validate(data)


def page(
    session: Session,
    statement,
    limit: int,
    offset: int,
    encryption_key: str | None = None,
) -> MemoryPage:
    rows = session.scalars(
        statement.order_by(Memory.created_at.desc(), Memory.id, Memory.version.desc())
        .offset(offset)
        .limit(limit + 1)
    ).all()
    return MemoryPage(
        items=[to_read_schema(row, encryption_key) for row in rows[:limit]],
        limit=limit,
        offset=offset,
        has_more=len(rows) > limit,
    )


@router.post("", response_model=MemoryRead, status_code=201)
def create_memory(
    payload: MemoryCreate,
    response: Response,
    session: Database,
    embedder: Embedder,
    request: Request,
    deduplicate: Annotated[bool | None, Query()] = None,
    api_key: ApiKeyDep = None,
):
    should_dedupe = deduplicate if deduplicate is not None else payload.deduplicate
    settings = request.app.state.settings
    verify_user_access(payload.user_id, api_key, settings)
    enc_key = settings.encryption_key.get_secret_value() if settings.encryption_key else None
    embedding = embedder.embed(payload.content)
    with session.begin():
        if should_dedupe:
            acquire_dedupe_lock(session, payload.user_id)
            memory, action, matched_id = deduplicate_and_store(
                session=session,
                user_id=payload.user_id,
                content=payload.content,
                memory_type=payload.type,
                importance=payload.importance,
                confidence=payload.confidence,
                source=payload.source,
                creation_reason=payload.creation_reason,
                metadata=payload.metadata,
                embedding_vector=embedding.vector,
                embedding_model=embedding.model,
                embedding_dimensions=embedding.dimensions,
                threshold=settings.dedupe_threshold,
            )
            data = to_read_schema(memory, enc_key).model_dump()
            data["action"] = action
            data["matched_memory_id"] = matched_id
            result = MemoryRead.model_validate(data)
            if action in ("consolidated", "ignored"):
                response.status_code = 200
        else:
            values = payload.model_dump(exclude={"metadata", "deduplicate"})
            if enc_key:
                values["content"] = encrypt_content(payload.content, enc_key)
            memory = Memory(
                **values,
                attributes=payload.metadata,
                embedding=embedding.vector,
                embedding_model=embedding.model,
                embedding_dimensions=embedding.dimensions,
            )
            session.add(memory)
            session.flush()
            record_event(
                session=session,
                user_id=payload.user_id,
                memory_id=memory.id,
                memory_version=memory.version,
                event_type="created",
                reason=payload.creation_reason,
                source=payload.source,
                actor="user",
                detail={"confidence": memory.confidence},
            )
            result = to_read_schema(memory, enc_key)
    response.headers["Location"] = f"/memories/{result.id}?{urlencode({'user_id': result.user_id})}"
    return result


@router.get("", response_model=MemoryPage)
def list_memories(
    user_id: Owner,
    session: Database,
    request: Request,
    api_key: ApiKeyDep = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
    type: MemoryType | None = None,
    status: CurrentStatus | None = None,
):
    settings = request.app.state.settings
    verify_user_access(user_id, api_key, settings)
    enc_key = settings.encryption_key.get_secret_value() if settings.encryption_key else None
    statement = current_query(user_id)
    if type is not None:
        statement = statement.where(Memory.type == type)
    if status is not None:
        statement = statement.where(Memory.status == status)
    with session.begin():
        return page(session, statement, limit, offset, encryption_key=enc_key)


@router.post("/search", response_model=MemoryPage)
def search_memories(
    payload: MemorySearch,
    session: Database,
    request: Request,
    api_key: ApiKeyDep = None,
):
    settings = request.app.state.settings
    verify_user_access(payload.user_id, api_key, settings)
    enc_key = settings.encryption_key.get_secret_value() if settings.encryption_key else None
    statement = current_query(payload.user_id).where(
        Memory.status == payload.status,
        Memory.content.icontains(payload.query, autoescape=True),
    )
    if payload.type is not None:
        statement = statement.where(Memory.type == payload.type)
    with session.begin():
        return page(session, statement, payload.limit, payload.offset, encryption_key=enc_key)


@router.post("/retrieve", response_model=MemoryRankedPage)
def retrieve_memories(
    payload: MemoryRetrieve,
    session: Database,
    embedder: Embedder,
    request: Request,
    api_key: ApiKeyDep = None,
):
    settings = request.app.state.settings
    verify_user_access(payload.user_id, api_key, settings)
    enc_key = settings.encryption_key.get_secret_value() if settings.encryption_key else None
    threshold = (
        payload.min_score if payload.min_score is not None else settings.retrieval_min_similarity
    )
    query_embedding = embedder.embed(payload.query, kind="query")
    semantic_relevance = 1.0 - Memory.embedding.cosine_distance(query_embedding.vector)

    candidate_multiplier = settings.rank_candidate_multiplier
    candidate_limit = payload.limit * candidate_multiplier

    statement = select(Memory, semantic_relevance.label("relevance")).where(
        Memory.user_id == payload.user_id,
        Memory.status == payload.status,
        Memory.embedding_model == embedder.model_id,
        Memory.embedding_dimensions == embedder.dimensions,
        semantic_relevance >= threshold,
    )
    if payload.type is not None:
        statement = statement.where(Memory.type == payload.type)

    statement = statement.order_by(semantic_relevance.desc()).limit(candidate_limit + 1)

    with session.begin():
        rows = session.execute(statement).all()
        has_more = len(rows) > payload.limit
        candidate_rows = rows[:candidate_limit]

        now = datetime.now(UTC)
        scored_candidates = []
        for memory, relevance in candidate_rows:
            recency = calculate_recency(
                memory.created_at, now, settings.rank_recency_half_life_days
            )
            frequency = calculate_frequency(memory.access_count, settings.rank_frequency_cap)
            score, breakdown = calculate_score(
                relevance=float(relevance),
                importance=float(memory.importance),
                confidence=float(memory.confidence),
                recency=recency,
                frequency=frequency,
                settings=settings,
            )
            scored_candidates.append((memory, score, breakdown))

        scored_candidates.sort(
            key=lambda x: (x[1], x[0].created_at, str(x[0].id)),
            reverse=True,
        )

        top_candidates = scored_candidates[: payload.limit]
        returned_ids = [m.id for m, _, _ in top_candidates]

        if payload.track_access and returned_ids:
            session.execute(
                update(Memory)
                .where(
                    Memory.id.in_(returned_ids),
                    Memory.status == payload.status,
                )
                .values(
                    access_count=Memory.access_count + 1,
                    last_accessed_at=func.now(),
                )
            )
            for mem, sc, _ in top_candidates:
                record_event(
                    session=session,
                    user_id=mem.user_id,
                    memory_id=mem.id,
                    memory_version=mem.version,
                    event_type="accessed",
                    reason=None,
                    source=mem.source,
                    actor="user",
                    detail={"query": payload.query, "score": sc},
                )

        items = []
        for memory, score, breakdown in top_candidates:
            items.append(to_ranked_schema(memory, score, breakdown, enc_key))

        return MemoryRankedPage(
            items=items,
            limit=payload.limit,
            has_more=has_more,
        )


@router.get("/{memory_id}", response_model=MemoryRead)
def get_memory(
    memory_id: UUID,
    user_id: Owner,
    session: Database,
    request: Request,
    api_key: ApiKeyDep = None,
):
    settings = request.app.state.settings
    verify_user_access(user_id, api_key, settings)
    enc_key = settings.encryption_key.get_secret_value() if settings.encryption_key else None
    with session.begin():
        return to_read_schema(current_memory(session, user_id, memory_id), enc_key)


@router.get("/{memory_id}/versions", response_model=MemoryPage)
def memory_history(
    memory_id: UUID,
    user_id: Owner,
    session: Database,
    request: Request,
    api_key: ApiKeyDep = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    settings = request.app.state.settings
    verify_user_access(user_id, api_key, settings)
    enc_key = settings.encryption_key.get_secret_value() if settings.encryption_key else None
    with session.begin():
        current_memory(session, user_id, memory_id)
        return page(
            session,
            select(Memory)
            .where(Memory.id == memory_id, Memory.user_id == user_id)
            .order_by(Memory.version.desc()),
            limit,
            offset,
            encryption_key=enc_key,
        )


@router.put("/{memory_id}", response_model=MemoryRead)
def update_memory(
    memory_id: UUID,
    user_id: Owner,
    payload: MemoryUpdate,
    session: Database,
    embedder: Embedder,
    request: Request,
    api_key: ApiKeyDep = None,
):
    settings = request.app.state.settings
    verify_user_access(user_id, api_key, settings)
    enc_key = settings.encryption_key.get_secret_value() if settings.encryption_key else None
    with session.begin():
        previous = current_memory(session, user_id, memory_id)
        if previous.version != payload.expected_version:
            raise HTTPException(409, "Memory version has changed; reload before updating")
        reusable = (
            previous.content == payload.content
            and previous.embedding is not None
            and previous.embedding_model == embedder.model_id
            and previous.embedding_dimensions == embedder.dimensions
        )
        cached = (
            (list(previous.embedding), previous.embedding_model, previous.embedding_dimensions)
            if reusable
            else None
        )
    embedding = None if reusable else embedder.embed(payload.content)
    with session.begin():
        lock_memory(session, user_id, memory_id)
        previous = current_memory(session, user_id, memory_id)
        if previous.version != payload.expected_version:
            raise HTTPException(409, "Memory version has changed; reload before updating")
        values = payload.model_dump(exclude={"expected_version", "metadata"})
        if enc_key:
            values["content"] = encrypt_content(payload.content, enc_key)
        memory = Memory(
            **values,
            id=previous.id,
            user_id=previous.user_id,
            version=previous.version + 1,
            previous_version=previous.version,
            attributes=payload.metadata,
        )
        if cached is not None:
            memory.embedding, memory.embedding_model, memory.embedding_dimensions = cached
        else:
            memory.embedding = embedding.vector
            memory.embedding_model = embedding.model
            memory.embedding_dimensions = embedding.dimensions
        prev_status = previous.status
        previous.status = "superseded"
        session.flush()
        session.add(memory)
        session.flush()
        if payload.status == "disabled":
            event_type = "disabled"
        elif prev_status == "disabled" and payload.status == "active":
            event_type = "enabled"
        else:
            event_type = "superseded"
        record_event(
            session=session,
            user_id=user_id,
            memory_id=memory.id,
            memory_version=memory.version,
            event_type=event_type,
            reason=payload.creation_reason,
            source=payload.source,
            actor="user",
            detail={"confidence": memory.confidence},
        )
        result = to_read_schema(memory, enc_key)
    return result


@router.delete("/{memory_id}", status_code=204)
def delete_memory(
    memory_id: UUID,
    user_id: Owner,
    session: Database,
    request: Request,
    api_key: ApiKeyDep = None,
):
    settings = request.app.state.settings
    verify_user_access(user_id, api_key, settings)
    with session.begin():
        lock_memory(session, user_id, memory_id)
        current = current_memory(session, user_id, memory_id)
        record_event(
            session=session,
            user_id=user_id,
            memory_id=memory_id,
            memory_version=current.version,
            event_type="deleted",
            reason=None,
            source=current.source,
            actor="user",
            detail={},
        )
        session.execute(delete(Memory).where(Memory.id == memory_id, Memory.user_id == user_id))
    return Response(status_code=204)


@router.get("/{memory_id}/provenance", response_model=MemoryProvenanceResponse)
def get_memory_provenance(
    memory_id: UUID,
    user_id: Owner,
    session: Database,
    request: Request,
    api_key: ApiKeyDep = None,
):
    settings = request.app.state.settings
    verify_user_access(user_id, api_key, settings)
    with session.begin():
        return get_memory_provenance_records(session, user_id, memory_id)


@router.post("/{memory_id}/disable", response_model=MemoryRead)
def disable_memory_endpoint(
    memory_id: UUID,
    user_id: Owner,
    session: Database,
    request: Request,
    api_key: ApiKeyDep = None,
):
    settings = request.app.state.settings
    verify_user_access(user_id, api_key, settings)
    enc_key = settings.encryption_key.get_secret_value() if settings.encryption_key else None
    with session.begin():
        lock_memory(session, user_id, memory_id)
        previous = current_memory(session, user_id, memory_id)
        if previous.status == "disabled":
            return to_read_schema(previous, enc_key)
        memory = Memory(
            id=previous.id,
            user_id=previous.user_id,
            version=previous.version + 1,
            previous_version=previous.version,
            content=previous.content,
            type=previous.type,
            importance=previous.importance,
            confidence=previous.confidence,
            source=previous.source,
            creation_reason=previous.creation_reason,
            status="disabled",
            attributes=dict(previous.attributes or {}),
            embedding=previous.embedding,
            embedding_model=previous.embedding_model,
            embedding_dimensions=previous.embedding_dimensions,
            access_count=previous.access_count,
            last_accessed_at=previous.last_accessed_at,
        )
        previous.status = "superseded"
        session.flush()
        session.add(memory)
        session.flush()
        record_event(
            session=session,
            user_id=user_id,
            memory_id=memory.id,
            memory_version=memory.version,
            event_type="disabled",
            reason=previous.creation_reason,
            source=previous.source,
            actor="user",
            detail={"confidence": memory.confidence},
        )
        return to_read_schema(memory, enc_key)


@router.post("/{memory_id}/enable", response_model=MemoryRead)
def enable_memory_endpoint(
    memory_id: UUID,
    user_id: Owner,
    session: Database,
    request: Request,
    api_key: ApiKeyDep = None,
):
    settings = request.app.state.settings
    verify_user_access(user_id, api_key, settings)
    enc_key = settings.encryption_key.get_secret_value() if settings.encryption_key else None
    with session.begin():
        lock_memory(session, user_id, memory_id)
        previous = current_memory(session, user_id, memory_id)
        if previous.status == "active":
            return to_read_schema(previous, enc_key)
        memory = Memory(
            id=previous.id,
            user_id=previous.user_id,
            version=previous.version + 1,
            previous_version=previous.version,
            content=previous.content,
            type=previous.type,
            importance=previous.importance,
            confidence=previous.confidence,
            source=previous.source,
            creation_reason=previous.creation_reason,
            status="active",
            attributes=dict(previous.attributes or {}),
            embedding=previous.embedding,
            embedding_model=previous.embedding_model,
            embedding_dimensions=previous.embedding_dimensions,
            access_count=previous.access_count,
            last_accessed_at=previous.last_accessed_at,
        )
        previous.status = "superseded"
        session.flush()
        session.add(memory)
        session.flush()
        record_event(
            session=session,
            user_id=user_id,
            memory_id=memory.id,
            memory_version=memory.version,
            event_type="enabled",
            reason=previous.creation_reason,
            source=previous.source,
            actor="user",
            detail={"confidence": memory.confidence},
        )
        return to_read_schema(memory, enc_key)
