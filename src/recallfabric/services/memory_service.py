from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from recallfabric.core.config import Settings
from recallfabric.db.models import Memory
from recallfabric.embeddings.service import EmbeddingProvider
from recallfabric.memory_manager.dedupe import acquire_dedupe_lock, deduplicate_and_store
from recallfabric.memory_manager.events import record_event
from recallfabric.ranking.scoring import (
    calculate_frequency,
    calculate_recency,
    calculate_score,
)
from recallfabric.security.encryption import decrypt_content, encrypt_content


def store_memory_service(
    session: Session,
    settings: Settings,
    embedder: EmbeddingProvider,
    user_id: str,
    content: str,
    type: str = "fact",
    importance: float = 0.5,
    confidence: float = 1.0,
    source: str = "mcp",
    deduplicate: bool = True,
    creation_reason: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    metadata = metadata or {}
    enc_key = settings.encryption_key.get_secret_value() if settings.encryption_key else None
    embedding = embedder.embed(content)

    if deduplicate:
        acquire_dedupe_lock(session, user_id)
        memory, action, matched_id = deduplicate_and_store(
            session=session,
            user_id=user_id,
            content=content,
            memory_type=type,
            importance=importance,
            confidence=confidence,
            source=source,
            creation_reason=creation_reason,
            metadata=metadata,
            embedding_vector=embedding.vector,
            embedding_model=embedding.model,
            embedding_dimensions=embedding.dimensions,
            threshold=settings.dedupe_threshold,
        )
        decrypted = decrypt_content(memory.content, enc_key) if enc_key else memory.content
        return {
            "id": str(memory.id),
            "user_id": memory.user_id,
            "content": decrypted,
            "type": memory.type,
            "importance": memory.importance,
            "confidence": memory.confidence,
            "source": memory.source,
            "version": memory.version,
            "previous_version": memory.previous_version,
            "status": memory.status,
            "metadata": memory.attributes or {},
            "created_at": memory.created_at.isoformat() if memory.created_at else None,
            "updated_at": memory.updated_at.isoformat() if memory.updated_at else None,
            "action": action,
            "matched_memory_id": str(matched_id) if matched_id else None,
        }

    stored_content = encrypt_content(content, enc_key) if enc_key else content
    memory = Memory(
        user_id=user_id,
        content=stored_content,
        type=type,
        importance=importance,
        confidence=confidence,
        source=source,
        creation_reason=creation_reason,
        attributes=metadata,
        embedding=embedding.vector,
        embedding_model=embedding.model,
        embedding_dimensions=embedding.dimensions,
    )
    session.add(memory)
    session.flush()
    record_event(
        session=session,
        user_id=user_id,
        memory_id=memory.id,
        memory_version=memory.version,
        event_type="created",
        reason=creation_reason,
        source=source,
        actor="user",
        detail={"confidence": memory.confidence},
    )
    decrypted = decrypt_content(memory.content, enc_key) if enc_key else memory.content
    return {
        "id": str(memory.id),
        "user_id": memory.user_id,
        "content": decrypted,
        "type": memory.type,
        "importance": memory.importance,
        "confidence": memory.confidence,
        "source": memory.source,
        "version": memory.version,
        "previous_version": memory.previous_version,
        "status": memory.status,
        "metadata": memory.attributes or {},
        "created_at": memory.created_at.isoformat() if memory.created_at else None,
        "updated_at": memory.updated_at.isoformat() if memory.updated_at else None,
        "action": "created",
        "matched_memory_id": None,
    }


def search_memory_service(
    session: Session,
    settings: Settings,
    embedder: EmbeddingProvider,
    user_id: str,
    query: str,
    limit: int = 20,
    type: str | None = None,
    status: str = "active",
) -> list[dict[str, Any]]:
    enc_key = settings.encryption_key.get_secret_value() if settings.encryption_key else None
    query_embedding = embedder.embed(query, kind="query")
    semantic_relevance = 1.0 - Memory.embedding.cosine_distance(query_embedding.vector)

    threshold = settings.retrieval_min_similarity
    candidate_limit = limit * settings.rank_candidate_multiplier

    statement = select(Memory, semantic_relevance.label("relevance")).where(
        Memory.user_id == user_id,
        Memory.status == status,
        Memory.embedding_model == embedder.model_id,
        Memory.embedding_dimensions == embedder.dimensions,
        semantic_relevance >= threshold,
    )
    if type is not None:
        statement = statement.where(Memory.type == type)

    statement = statement.order_by(semantic_relevance.desc()).limit(candidate_limit + 1)
    rows = session.execute(statement).all()
    candidate_rows = rows[:candidate_limit]

    now = datetime.now(UTC)
    scored = []
    seen_ids = set()
    for mem, rel in candidate_rows:
        recency = calculate_recency(mem.created_at, now, settings.rank_recency_half_life_days)
        freq = calculate_frequency(mem.access_count, settings.rank_frequency_cap)
        score, breakdown = calculate_score(
            relevance=float(rel),
            importance=float(mem.importance),
            confidence=float(mem.confidence),
            recency=recency,
            frequency=freq,
            settings=settings,
        )
        scored.append((mem, score, breakdown))
        seen_ids.add(mem.id)

    scored.sort(key=lambda x: (x[1], x[0].created_at, str(x[0].id)), reverse=True)
    top = scored[:limit]

    results = []
    for mem, score, breakdown in top:
        decrypted = decrypt_content(mem.content, enc_key) if enc_key else mem.content
        results.append(
            {
                "id": str(mem.id),
                "user_id": mem.user_id,
                "content": decrypted,
                "type": mem.type,
                "importance": mem.importance,
                "confidence": mem.confidence,
                "source": mem.source,
                "version": mem.version,
                "status": mem.status,
                "score": score,
                "score_breakdown": breakdown.model_dump(),
                "metadata": mem.attributes or {},
                "created_at": mem.created_at.isoformat() if mem.created_at else None,
                "updated_at": mem.updated_at.isoformat() if mem.updated_at else None,
            }
        )

    if len(results) < limit:
        text_stmt = select(Memory).where(
            Memory.user_id == user_id,
            Memory.status == status,
            Memory.content.icontains(query, autoescape=True),
        )
        if type is not None:
            text_stmt = text_stmt.where(Memory.type == type)
        text_stmt = text_stmt.order_by(Memory.created_at.desc()).limit(limit - len(results))
        for text_mem in session.scalars(text_stmt).all():
            if text_mem.id not in seen_ids:
                decrypted = (
                    decrypt_content(text_mem.content, enc_key) if enc_key else text_mem.content
                )
                results.append(
                    {
                        "id": str(text_mem.id),
                        "user_id": text_mem.user_id,
                        "content": decrypted,
                        "type": text_mem.type,
                        "importance": text_mem.importance,
                        "confidence": text_mem.confidence,
                        "source": text_mem.source,
                        "version": text_mem.version,
                        "status": text_mem.status,
                        "score": 0.5,
                        "score_breakdown": {},
                        "metadata": text_mem.attributes or {},
                        "created_at": (
                            text_mem.created_at.isoformat() if text_mem.created_at else None
                        ),
                        "updated_at": (
                            text_mem.updated_at.isoformat() if text_mem.updated_at else None
                        ),
                    }
                )
                seen_ids.add(text_mem.id)

    return results


def update_memory_service(
    session: Session,
    settings: Settings,
    embedder: EmbeddingProvider,
    user_id: str,
    memory_id: str | UUID,
    content: str,
    expected_version: int,
    type: str = "fact",
    source: str = "mcp",
    status: str = "active",
    creation_reason: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if isinstance(memory_id, str):
        memory_id = UUID(memory_id)
    metadata = metadata or {}
    enc_key = settings.encryption_key.get_secret_value() if settings.encryption_key else None

    previous = session.scalar(
        select(Memory).where(
            Memory.id == memory_id,
            Memory.user_id == user_id,
            Memory.status.in_(["active", "disabled"]),
        )
    )
    if previous is None:
        raise ValueError("Memory not found")
    if previous.version != expected_version:
        raise ValueError(
            f"Version mismatch: expected {expected_version}, current {previous.version}"
        )

    reusable = (
        previous.content == content
        and previous.embedding is not None
        and previous.embedding_model == embedder.model_id
        and previous.embedding_dimensions == embedder.dimensions
    )
    cached = (
        (list(previous.embedding), previous.embedding_model, previous.embedding_dimensions)
        if reusable
        else None
    )
    embedding = None if reusable else embedder.embed(content)

    stored_content = encrypt_content(content, enc_key) if enc_key else content
    previous.status = "superseded"
    session.flush()

    new_mem = Memory(
        id=previous.id,
        user_id=user_id,
        content=stored_content,
        type=type,
        importance=previous.importance,
        confidence=previous.confidence,
        source=source,
        version=previous.version + 1,
        previous_version=previous.version,
        status=status,
        creation_reason=creation_reason,
        attributes=metadata,
    )
    if cached is not None:
        new_mem.embedding, new_mem.embedding_model, new_mem.embedding_dimensions = cached
    else:
        new_mem.embedding = embedding.vector
        new_mem.embedding_model = embedding.model
        new_mem.embedding_dimensions = embedding.dimensions

    session.add(new_mem)
    session.flush()

    record_event(
        session=session,
        user_id=user_id,
        memory_id=new_mem.id,
        memory_version=new_mem.version,
        event_type="superseded",
        reason=creation_reason,
        source=source,
        actor="user",
        detail={"confidence": new_mem.confidence},
    )

    decrypted = decrypt_content(new_mem.content, enc_key) if enc_key else new_mem.content
    return {
        "id": str(new_mem.id),
        "user_id": new_mem.user_id,
        "content": decrypted,
        "type": new_mem.type,
        "importance": new_mem.importance,
        "confidence": new_mem.confidence,
        "source": new_mem.source,
        "version": new_mem.version,
        "previous_version": new_mem.previous_version,
        "status": new_mem.status,
        "metadata": new_mem.attributes or {},
        "created_at": new_mem.created_at.isoformat() if new_mem.created_at else None,
        "updated_at": new_mem.updated_at.isoformat() if new_mem.updated_at else None,
    }


def delete_memory_service(
    session: Session,
    settings: Settings,
    user_id: str,
    memory_id: str | UUID,
) -> dict[str, Any]:
    if isinstance(memory_id, str):
        memory_id = UUID(memory_id)

    current = session.scalar(
        select(Memory).where(
            Memory.id == memory_id,
            Memory.user_id == user_id,
            Memory.status.in_(["active", "disabled"]),
        )
    )
    if current is None:
        raise ValueError("Memory not found")

    record_event(
        session=session,
        user_id=user_id,
        memory_id=current.id,
        memory_version=current.version,
        event_type="deleted",
        reason="MCP delete request",
        source=current.source,
        actor="user",
        detail={},
    )

    session.execute(delete(Memory).where(Memory.user_id == user_id, Memory.id == memory_id))
    session.flush()
    return {"deleted": True, "id": str(memory_id)}


def list_memories_service(
    session: Session,
    settings: Settings,
    user_id: str,
    type: str | None = None,
    status: str = "active",
    limit: int = 20,
    offset: int = 0,
) -> list[dict[str, Any]]:
    enc_key = settings.encryption_key.get_secret_value() if settings.encryption_key else None
    statement = (
        select(Memory)
        .where(Memory.user_id == user_id, Memory.status == status)
        .order_by(Memory.created_at.desc(), Memory.version.desc())
        .offset(offset)
        .limit(limit)
    )
    if type is not None:
        statement = statement.where(Memory.type == type)

    rows = session.scalars(statement).all()
    results = []
    for mem in rows:
        decrypted = decrypt_content(mem.content, enc_key) if enc_key else mem.content
        results.append(
            {
                "id": str(mem.id),
                "user_id": mem.user_id,
                "content": decrypted,
                "type": mem.type,
                "importance": mem.importance,
                "confidence": mem.confidence,
                "source": mem.source,
                "version": mem.version,
                "previous_version": mem.previous_version,
                "status": mem.status,
                "metadata": mem.attributes or {},
                "created_at": mem.created_at.isoformat() if mem.created_at else None,
                "updated_at": mem.updated_at.isoformat() if mem.updated_at else None,
            }
        )
    return results


def get_memory_history_service(
    session: Session,
    settings: Settings,
    user_id: str,
    memory_id: str | UUID,
    limit: int = 20,
    offset: int = 0,
) -> list[dict[str, Any]]:
    if isinstance(memory_id, str):
        memory_id = UUID(memory_id)
    enc_key = settings.encryption_key.get_secret_value() if settings.encryption_key else None
    statement = (
        select(Memory)
        .where(Memory.user_id == user_id, Memory.id == memory_id)
        .order_by(Memory.version.desc())
        .offset(offset)
        .limit(limit)
    )
    rows = session.scalars(statement).all()
    results = []
    for mem in rows:
        decrypted = decrypt_content(mem.content, enc_key) if enc_key else mem.content
        results.append(
            {
                "id": str(mem.id),
                "user_id": mem.user_id,
                "content": decrypted,
                "type": mem.type,
                "importance": mem.importance,
                "confidence": mem.confidence,
                "source": mem.source,
                "version": mem.version,
                "previous_version": mem.previous_version,
                "status": mem.status,
                "metadata": mem.attributes or {},
                "created_at": mem.created_at.isoformat() if mem.created_at else None,
                "updated_at": mem.updated_at.isoformat() if mem.updated_at else None,
            }
        )
    return results
