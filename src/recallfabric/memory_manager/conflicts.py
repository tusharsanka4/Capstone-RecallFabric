import json
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from recallfabric.db.models import Memory
from recallfabric.memory_manager.events import record_event
from recallfabric.security.encryption import decrypt_content, encrypt_content

CONFLICT_SYSTEM_PROMPT = (
    "You are an AI memory manager analyzing if a new memory updates or contradicts an old one.\n"
    "Classify into:\n"
    "- 'update': new memory updates, replaces, or contradicts existing memory "
    "(e.g. learning Django updates learning Spring Boot; "
    "moving to London updates living in Paris).\n"
    "- 'duplicate': both express the same fact or meaning.\n"
    "- 'unrelated': both memories are distinct facts that can both be true simultaneously.\n"
    "Respond strictly with valid JSON: "
    '{"classification": "update" | "duplicate" | "unrelated", "reason": "brief explanation"}'
)


def find_conflict_candidates(
    session: Session,
    user_id: str,
    memory_type: str,
    embedding_vector: list[float],
    embedding_model: str,
    embedding_dimensions: int,
    min_similarity: float,
    max_similarity: float,
) -> list[tuple[Memory, float]]:
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
                similarity >= min_similarity,
                similarity < max_similarity,
            )
            .order_by(similarity.desc())
            .limit(5)
        )
        rows = session.execute(statement).all()
        results = []
        for row in rows:
            if hasattr(row, "__len__") and len(row) == 2:
                mem, sim = row[0], row[1]
                if isinstance(mem, Memory) and isinstance(sim, (int, float)):
                    results.append((mem, float(sim)))
        return results
    except Exception:
        return []


def classify_conflict(
    llm: Any,
    model: str,
    existing_content: str,
    new_content: str,
    memory_type: str,
    timeout: float = 10.0,
) -> str:
    user_message = (
        f"Existing memory: {existing_content}\n"
        f"New memory: {new_content}\n"
        f"Memory type: {memory_type}"
    )
    messages = [
        {"role": "system", "content": CONFLICT_SYSTEM_PROMPT},
        {"role": "user", "content": user_message},
    ]
    if hasattr(llm, "chat") and callable(llm.chat) and not hasattr(llm.chat, "completions"):
        content = llm.chat(messages=messages, temperature=0.0, json_mode=True)
    else:
        response = llm.chat.completions.create(
            model=model,
            messages=messages,
            response_format={"type": "json_object"},
            temperature=0.0,
            timeout=timeout,
        )
        choices = getattr(response, "choices", None)
        if not choices:
            raise ValueError("No choices in LLM response")
        message = getattr(choices[0], "message", None)
        content = getattr(message, "content", None)
        if not content:
            raise ValueError("Empty content in LLM response")
    data = json.loads(content)
    raw_class = str(data.get("classification", "")).lower().strip()
    if raw_class in ("update", "contradiction", "contradiction/update"):
        return "update"
    if raw_class == "duplicate":
        return "duplicate"
    return "unrelated"


def resolve_conflict_or_store(
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
    min_similarity: float,
    max_similarity: float,
    llm: Any | None,
    llm_model: str,
    llm_timeout: float = 10.0,
) -> tuple[Memory, Literal["created", "consolidated"], UUID | None, dict[str, Any] | None]:
    candidates = find_conflict_candidates(
        session=session,
        user_id=user_id,
        memory_type=memory_type,
        embedding_vector=embedding_vector,
        embedding_model=embedding_model,
        embedding_dimensions=embedding_dimensions,
        min_similarity=min_similarity,
        max_similarity=max_similarity,
    )

    if not candidates:
        new_meta = dict(metadata or {})
        sources = list(new_meta.get("sources") or [])
        if source and source not in sources:
            sources.append(source)
        new_meta["sources"] = sources
        new_memory = Memory(
            user_id=user_id,
            content=encrypt_content(content),
            type=memory_type,
            importance=importance,
            confidence=confidence,
            source=source,
            creation_reason=creation_reason,
            attributes=new_meta,
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
        return new_memory, "created", None, None

    if llm is None:
        new_meta = dict(metadata or {})
        new_meta["conflict_check"] = "skipped"
        sources = list(new_meta.get("sources") or [])
        if source and source not in sources:
            sources.append(source)
        new_meta["sources"] = sources
        new_memory = Memory(
            user_id=user_id,
            content=encrypt_content(content),
            type=memory_type,
            importance=importance,
            confidence=confidence,
            source=source,
            creation_reason=creation_reason,
            attributes=new_meta,
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
        return new_memory, "created", None, None

    for candidate, _ in candidates:
        try:
            decrypted_candidate_content = decrypt_content(candidate.content)
            classification = classify_conflict(
                llm=llm,
                model=llm_model,
                existing_content=decrypted_candidate_content,
                new_content=content,
                memory_type=memory_type,
                timeout=llm_timeout,
            )
        except Exception:
            new_meta = dict(metadata or {})
            new_meta["conflict_check"] = "skipped"
            sources = list(new_meta.get("sources") or [])
            if source and source not in sources:
                sources.append(source)
            new_meta["sources"] = sources
            new_memory = Memory(
                user_id=user_id,
                content=encrypt_content(content),
                type=memory_type,
                importance=importance,
                confidence=confidence,
                source=source,
                creation_reason=creation_reason,
                attributes=new_meta,
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
            return new_memory, "created", None, None

        if classification == "update":
            candidate.status = "superseded"
            session.flush()

            merged_importance = max(float(candidate.importance), float(importance))
            merged_confidence = max(float(candidate.confidence), float(confidence))

            merged_metadata = dict(candidate.attributes or {})
            sources = list(merged_metadata.get("sources") or [])
            if not sources and candidate.source:
                sources.append(candidate.source)
            if source and source not in sources:
                sources.append(source)
            if metadata:
                for k, v in metadata.items():
                    if k != "sources":
                        merged_metadata[k] = v
            merged_metadata["sources"] = sources

            update_reason = f"Updated from: {decrypted_candidate_content}"
            new_revision = Memory(
                id=candidate.id,
                user_id=candidate.user_id,
                version=candidate.version + 1,
                previous_version=candidate.version,
                status="active",
                content=encrypt_content(content),
                type=memory_type,
                importance=merged_importance,
                confidence=merged_confidence,
                source=source,
                creation_reason=update_reason,
                attributes=merged_metadata,
                embedding=embedding_vector,
                embedding_model=embedding_model,
                embedding_dimensions=embedding_dimensions,
                access_count=candidate.access_count + 1,
                last_accessed_at=datetime.now(UTC),
            )
            session.add(new_revision)
            session.flush()
            resolution = {
                "superseded_id": str(candidate.id),
                "previous_content": decrypted_candidate_content,
                "reason": update_reason,
            }
            record_event(
                session=session,
                user_id=new_revision.user_id,
                memory_id=new_revision.id,
                memory_version=new_revision.version,
                event_type="superseded",
                reason=update_reason,
                source=source,
                actor="user",
                detail={"confidence": merged_confidence, "conflict_resolution": resolution},
            )
            return new_revision, "consolidated", candidate.id, resolution

    new_meta = dict(metadata or {})
    sources = list(new_meta.get("sources") or [])
    if source and source not in sources:
        sources.append(source)
    new_meta["sources"] = sources
    new_memory = Memory(
        user_id=user_id,
        content=encrypt_content(content),
        type=memory_type,
        importance=importance,
        confidence=confidence,
        source=source,
        creation_reason=creation_reason,
        attributes=new_meta,
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
    return new_memory, "created", None, None
