"""User-scoped memory CRUD and basic text search."""

from typing import Annotated, Literal
from urllib.parse import urlencode
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from recallfabric.db.models import Memory
from recallfabric.db.session import get_session
from recallfabric.embeddings.service import EmbeddingProvider, get_embedding_provider
from recallfabric.schemas.memory import (
    MemoryCreate,
    MemoryPage,
    MemoryRead,
    MemorySearch,
    MemoryType,
    MemoryUpdate,
)

router = APIRouter(prefix="/memories", tags=["memories"])
Database = Annotated[Session, Depends(get_session)]
Embedder = Annotated[EmbeddingProvider, Depends(get_embedding_provider)]
Owner = Annotated[str, Query(min_length=1, max_length=255, pattern=r"\S")]
CurrentStatus = Literal["active", "disabled"]


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


def page(session: Session, statement, limit: int, offset: int) -> MemoryPage:
    rows = session.scalars(
        statement.order_by(Memory.created_at.desc(), Memory.id, Memory.version.desc())
        .offset(offset)
        .limit(limit + 1)
    ).all()
    return MemoryPage(
        items=[MemoryRead.model_validate(row) for row in rows[:limit]],
        limit=limit,
        offset=offset,
        has_more=len(rows) > limit,
    )


@router.post("", response_model=MemoryRead, status_code=201)
def create_memory(payload: MemoryCreate, response: Response, session: Database, embedder: Embedder):
    values = payload.model_dump(exclude={"metadata"})
    embedding = embedder.embed(payload.content)
    with session.begin():
        memory = Memory(
            **values,
            attributes=payload.metadata,
            embedding=embedding.vector,
            embedding_model=embedding.model,
            embedding_dimensions=embedding.dimensions,
        )
        session.add(memory)
        session.flush()
        result = MemoryRead.model_validate(memory)
    response.headers["Location"] = f"/memories/{result.id}?{urlencode({'user_id': result.user_id})}"
    return result


@router.get("", response_model=MemoryPage)
def list_memories(
    user_id: Owner,
    session: Database,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
    type: MemoryType | None = None,
    status: CurrentStatus | None = None,
):
    statement = current_query(user_id)
    if type is not None:
        statement = statement.where(Memory.type == type)
    if status is not None:
        statement = statement.where(Memory.status == status)
    with session.begin():
        return page(session, statement, limit, offset)


@router.post("/search", response_model=MemoryPage)
def search_memories(payload: MemorySearch, session: Database):
    """Case-insensitive literal substring search; semantic retrieval follows later."""
    statement = current_query(payload.user_id).where(
        Memory.status == payload.status,
        Memory.content.icontains(payload.query, autoescape=True),
    )
    if payload.type is not None:
        statement = statement.where(Memory.type == payload.type)
    with session.begin():
        return page(session, statement, payload.limit, payload.offset)


@router.get("/{memory_id}", response_model=MemoryRead)
def get_memory(memory_id: UUID, user_id: Owner, session: Database):
    with session.begin():
        return MemoryRead.model_validate(current_memory(session, user_id, memory_id))


@router.get("/{memory_id}/versions", response_model=MemoryPage)
def memory_history(
    memory_id: UUID,
    user_id: Owner,
    session: Database,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    with session.begin():
        current_memory(session, user_id, memory_id)
        return page(
            session,
            select(Memory)
            .where(Memory.id == memory_id, Memory.user_id == user_id)
            .order_by(Memory.version.desc()),
            limit,
            offset,
        )


@router.put("/{memory_id}", response_model=MemoryRead)
def update_memory(
    memory_id: UUID, user_id: Owner, payload: MemoryUpdate, session: Database, embedder: Embedder
):
    # Check ownership/version before inference, without holding a DB lock while it runs.
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
        previous.status = "superseded"
        session.flush()
        session.add(memory)
        session.flush()
        result = MemoryRead.model_validate(memory)
    return result


@router.delete("/{memory_id}", status_code=204)
def delete_memory(memory_id: UUID, user_id: Owner, session: Database):
    with session.begin():
        lock_memory(session, user_id, memory_id)
        session.execute(delete(Memory).where(Memory.id == memory_id, Memory.user_id == user_id))
    return Response(status_code=204)
