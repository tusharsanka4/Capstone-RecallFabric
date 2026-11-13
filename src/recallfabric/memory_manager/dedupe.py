from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from recallfabric.db.models import Memory
from recallfabric.memory_manager.events import record_event
from recallfabric.security.encryption import decrypt_content, encrypt_content


def acquire_dedupe_lock(session: Session, user_id: str) -> None:
    try:
        bind = session.get_bind()
        if bind and bind.dialect.name == "postgresql":
            session.execute(
                text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
                {"key": f"dedupe:{user_id}"},
            )
    except Exception:
        pass


def find_duplicate_memory(
    session: Session,
    user_id: str,
    memory_type: str,
    embedding_vector: list[float],
    embedding_model: str,
    embedding_dimensions: int,
    threshold: float,
) -> tuple[Memory | None, float | None]:
    try:
        similarity = (1.0 - Memory.embedding.cosine_distance(embedding_vector)).label("similarity")
        statement = (
            select(Memory, similarity)
            .where(
                Memory.user_id == user_id,
                Memory.type == memory_type,
                Memory.status == "active",
                Memory.embedding_model == embedding_model,
                Memory.embedding_dimensions == embedding_dimensions,
            )
            .order_by(similarity.desc())
            .limit(1)
        )
        row = session.execute(statement).first()
        if row is not None:
            if hasattr(row, "__len__") and len(row) == 2:
                memory, sim = row[0], row[1]
                if isinstance(memory, Memory) and isinstance(sim, (int, float)):
                    if float(sim) >= threshold:
                        return memory, float(sim)
    except Exception:
        pass
    return None, None


def deduplicate_and_store(
    session: Session,
    user_id: str,
    content: str,
    memory_type: str,
    importance: float,
    confidence: float,
    source: str,
    creation_reason: str | None,
    metadata: dict[str, Any] | None,
    embedding_vector: list[float],
    embedding_model: str,
    embedding_dimensions: int,
    threshold: float,
) -> tuple[Memory, Literal["created", "consolidated", "ignored"], UUID | None]:
    matched, _ = find_duplicate_memory(
        session=session,
        user_id=user_id,
        memory_type=memory_type,
        embedding_vector=embedding_vector,
        embedding_model=embedding_model,
        embedding_dimensions=embedding_dimensions,
        threshold=threshold,
    )

    if matched is not None:
        matched_content = decrypt_content(matched.content)
        is_identical = matched_content.strip().lower() == content.strip().lower()
        merged_importance = max(float(matched.importance), float(importance))
        merged_confidence = max(float(matched.confidence), float(confidence))

        merged_metadata = dict(matched.attributes or {})
        sources = list(merged_metadata.get("sources") or [])
        if not sources and matched.source:
            sources.append(matched.source)
        if source and source not in sources:
            sources.append(source)
        if metadata:
            for k, v in metadata.items():
                if k != "sources":
                    merged_metadata[k] = v
        merged_metadata["sources"] = sources

        if is_identical:
            matched.importance = merged_importance
            matched.confidence = merged_confidence
            matched.access_count += 1
            matched.last_accessed_at = datetime.now(UTC)
            matched.attributes = merged_metadata
            session.flush()
            record_event(
                session=session,
                user_id=user_id,
                memory_id=matched.id,
                memory_version=matched.version,
                event_type="accessed",
                reason=None,
                source=source,
                actor="user",
                detail={"reason": "identical_duplicate"},
            )
            return matched, "ignored", matched.id

        matched.status = "superseded"
        session.flush()

        new_revision = Memory(
            id=matched.id,
            user_id=matched.user_id,
            version=matched.version + 1,
            previous_version=matched.version,
            status="active",
            content=encrypt_content(content),
            type=memory_type,
            importance=merged_importance,
            confidence=merged_confidence,
            source=source,
            creation_reason=creation_reason or matched.creation_reason,
            attributes=merged_metadata,
            embedding=embedding_vector,
            embedding_model=embedding_model,
            embedding_dimensions=embedding_dimensions,
            access_count=matched.access_count + 1,
            last_accessed_at=datetime.now(UTC),
        )
        session.add(new_revision)
        session.flush()
        record_event(
            session=session,
            user_id=user_id,
            memory_id=new_revision.id,
            memory_version=new_revision.version,
            event_type="consolidated",
            reason=new_revision.creation_reason,
            source=source,
            actor="user",
            detail={"confidence": merged_confidence},
        )
        return new_revision, "consolidated", matched.id

    new_metadata = dict(metadata or {})
    sources = list(new_metadata.get("sources") or [])
    if source and source not in sources:
        sources.append(source)
    new_metadata["sources"] = sources

    new_memory = Memory(
        user_id=user_id,
        content=encrypt_content(content),
        type=memory_type,
        importance=importance,
        confidence=confidence,
        source=source,
        creation_reason=creation_reason,
        attributes=new_metadata,
        embedding=embedding_vector,
        embedding_model=embedding_model,
        embedding_dimensions=embedding_dimensions,
    )
    session.add(new_memory)
    session.flush()
    record_event(
        session=session,
        user_id=user_id,
        memory_id=new_memory.id,
        memory_version=new_memory.version,
        event_type="created",
        reason=creation_reason,
        source=source,
        actor="user",
        detail={"confidence": confidence},
    )
    return new_memory, "created", None
