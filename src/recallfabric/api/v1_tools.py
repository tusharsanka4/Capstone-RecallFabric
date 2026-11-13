"""Task-oriented AI tool endpoints.

Endpoints include /v1/remember, /v1/recall, /v1/forget, /v1/profile, /v1/capabilities.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from importlib.metadata import version
from typing import Annotated, Any

from fastapi import APIRouter, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import delete, select

from recallfabric.api.memories import (
    ApiKeyDep,
    Database,
    Embedder,
    current_memory,
    lock_memory,
    to_read_schema,
)
from recallfabric.context.builder import build_context
from recallfabric.core.idempotency import default_idempotency_store
from recallfabric.db.models import Memory
from recallfabric.extraction.filters import filter_candidate
from recallfabric.memory_manager.conflicts import resolve_conflict_or_store
from recallfabric.memory_manager.dedupe import (
    acquire_dedupe_lock,
    deduplicate_and_store,
    find_duplicate_memory,
)
from recallfabric.memory_manager.events import record_event
from recallfabric.providers import get_extraction_provider
from recallfabric.ranking.scoring import (
    calculate_frequency,
    calculate_recency,
    calculate_score,
)
from recallfabric.schemas.memory import MemoryRead
from recallfabric.schemas.v1_tools import (
    CapabilitiesResponse,
    ForgetRequest,
    ForgetResponse,
    ProfileResponse,
    RecallMemoryItem,
    RecallRequest,
    RecallResponse,
    RememberRequest,
    RememberResponse,
)

router = APIRouter(tags=["tools"])


def _resolve_user_id(
    requested_user_id: str | None,
    api_key: ApiKeyDep,
    settings: Any,
) -> str:
    """Derive user_id safely from API key when auth is enabled, or use provided default."""
    if settings.auth_enabled:
        if api_key is None:
            raise HTTPException(status_code=401, detail="Authentication required.")
        if api_key.user_id:
            # If caller supplied a different user_id, refuse
            if requested_user_id and requested_user_id != api_key.user_id:
                raise HTTPException(
                    status_code=403,
                    detail=f"API key is restricted to user '{api_key.user_id}'.",
                )
            return api_key.user_id
        # Admin / unconstrained key
        if requested_user_id:
            return requested_user_id
        raise HTTPException(
            status_code=400,
            detail="user_id must be provided for unconstrained admin keys.",
        )

    # Auth disabled: fallback to requested_user_id or default_user
    if requested_user_id and requested_user_id.strip():
        return requested_user_id.strip()
    return "default_user"


@router.get(
    "/capabilities",
    response_model=CapabilitiesResponse,
    operation_id="capabilities",
    summary="Get service capabilities and active models",
    description=(
        "Inspect service version, active embedding model details, supported memory categories, "
        "enabled security features, and operational limits."
    ),
)
def get_capabilities(
    request: Request,
    embedder: Embedder,
) -> CapabilitiesResponse:
    settings = request.app.state.settings
    try:
        svc_version = version("recallfabric")
    except Exception:
        svc_version = "0.1.0"

    has_enc = bool(settings.encryption_key and settings.encryption_key.get_secret_value().strip())

    return CapabilitiesResponse(
        service_version=svc_version,
        supported_memory_types=[
            "preference",
            "goal",
            "skill",
            "profile",
            "fact",
            "other",
        ],
        embedding_model=embedder.model_id,
        embedding_dimensions=embedder.dimensions,
        enabled_features={
            "auth": bool(settings.auth_enabled),
            "encryption": has_enc,
            "rate_limiting": True,
            "provenance": True,
            "hybrid_ranking": True,
            "deduplication": True,
            "conflict_resolution": True,
        },
        limits={
            "rate_limit_rps": settings.rate_limit_rps,
            "rate_limit_burst": settings.rate_limit_burst,
            "max_request_size_bytes": settings.max_request_size_bytes,
            "context_max_chars": settings.context_max_chars,
            "chat_retrieval_limit": settings.chat_retrieval_limit,
        },
    )


@router.post(
    "/remember",
    response_model=RememberResponse,
    operation_id="remember",
    summary="Store a memory or extract facts from conversation",
    description=(
        "Store an explicit memory statement or extract atomic facts from conversation text. "
        "Use `content` for direct storage (preferences, facts, goals, etc.) with automatic "
        "deduplication and conflict superseding. Set `extract=true` to automatically analyze "
        "conversation turns and extract isolated facts."
    ),
)
def remember(
    payload: RememberRequest,
    session: Database,
    embedder: Embedder,
    request: Request,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    api_key: ApiKeyDep = None,
) -> Any:
    settings = request.app.state.settings
    user_id = _resolve_user_id(payload.user_id, api_key, settings)
    enc_key = settings.encryption_key.get_secret_value() if settings.encryption_key else None

    # 1. Idempotency check
    if idempotency_key:
        cached = default_idempotency_store.get(user_id, idempotency_key)
        if cached:
            return JSONResponse(
                status_code=cached.status_code,
                content=cached.content,
                headers={"X-Idempotent-Replay": "true"},
            )

    # 2. Validate content presence
    raw_text = payload.content if payload.content is not None else payload.text
    if not raw_text or not raw_text.strip():
        raise HTTPException(
            status_code=422,
            detail="Either 'content' or 'text' must be provided and non-empty.",
        )
    raw_text = raw_text.strip()

    # 3. Automatic Extraction Mode
    if payload.extract:
        # Use existing extraction routine
        provider = get_extraction_provider(settings)
        from recallfabric.extraction.prompt import SYSTEM_PROMPT

        user_prompt = f"Text to analyze:\n{raw_text}"
        try:
            result_content = provider.generate_sync(
                system_prompt=SYSTEM_PROMPT,
                user_prompt=user_prompt,
                model=settings.extraction_model,
                temperature=settings.extraction_temperature,
                timeout=settings.llm_timeout,
            )
            data = json.loads(result_content)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=502, detail="LLM returned invalid JSON") from exc

        candidates_data = data.get("memories", []) if isinstance(data, dict) else []
        created_memories: list[MemoryRead] = []

        valid_candidates = []
        for item in candidates_data:
            if not isinstance(item, dict):
                continue
            c_text = str(item.get("content", "")).strip().strip('"').strip("'").strip()
            try:
                imp = float(item.get("importance", 0.5))
                conf = float(item.get("confidence", 1.0))
            except (ValueError, TypeError):
                continue
            m_type = str(item.get("type", "fact")).lower().strip()
            if m_type not in {"preference", "goal", "skill", "profile", "fact", "other"}:
                m_type = "fact"

            is_valid, _ = filter_candidate(c_text, imp, conf, settings)
            if not is_valid:
                continue

            reason = str(item.get("creation_reason") or "").strip() or "Extracted from text"
            valid_candidates.append((c_text, m_type, imp, conf, reason))

        if valid_candidates:
            with session.begin():
                acquire_dedupe_lock(session, user_id)
                for c_text, m_type, imp, conf, reason in valid_candidates:
                    emb = embedder.embed(c_text)
                    matched, _ = find_duplicate_memory(
                        session=session,
                        user_id=user_id,
                        memory_type=m_type,
                        embedding_vector=emb.vector,
                        embedding_model=emb.model,
                        embedding_dimensions=emb.dimensions,
                        threshold=settings.dedupe_threshold,
                    )
                    if matched is not None:
                        mem, action, _ = deduplicate_and_store(
                            session=session,
                            user_id=user_id,
                            content=c_text,
                            memory_type=m_type,
                            importance=imp,
                            confidence=conf,
                            source=payload.source,
                            creation_reason=reason,
                            metadata=payload.metadata,
                            embedding_vector=emb.vector,
                            embedding_model=emb.model,
                            embedding_dimensions=emb.dimensions,
                            threshold=settings.dedupe_threshold,
                        )
                    else:
                        mem, action, _, _ = resolve_conflict_or_store(
                            session=session,
                            user_id=user_id,
                            content=c_text,
                            memory_type=m_type,
                            importance=imp,
                            confidence=conf,
                            source=payload.source,
                            creation_reason=reason,
                            metadata=payload.metadata,
                            embedding_vector=emb.vector,
                            embedding_model=emb.model,
                            embedding_dimensions=emb.dimensions,
                            min_similarity=settings.conflict_min_similarity,
                            max_similarity=settings.dedupe_threshold,
                            llm=provider,
                            llm_model=settings.extraction_model,
                            llm_timeout=settings.llm_timeout,
                        )
                    created_memories.append(to_read_schema(mem, enc_key))

        resp_obj = RememberResponse(
            status="extracted",
            action="extracted",
            memory=created_memories[0] if created_memories else None,
            memories=created_memories,
            count=len(created_memories),
            message=f"Extracted and processed {len(created_memories)} memories.",
        )
        if idempotency_key:
            default_idempotency_store.set(
                user_id, idempotency_key, 200, resp_obj.model_dump(mode="json")
            )
        return resp_obj

    # 4. Explicit Direct Memory Storage Mode
    importance = payload.importance if payload.importance is not None else 0.5
    confidence = payload.confidence
    emb = embedder.embed(raw_text)

    with session.begin():
        acquire_dedupe_lock(session, user_id)
        matched, _ = find_duplicate_memory(
            session=session,
            user_id=user_id,
            memory_type=payload.type,
            embedding_vector=emb.vector,
            embedding_model=emb.model,
            embedding_dimensions=emb.dimensions,
            threshold=settings.dedupe_threshold,
        )
        if matched is not None:
            mem, action, _ = deduplicate_and_store(
                session=session,
                user_id=user_id,
                content=raw_text,
                memory_type=payload.type,
                importance=importance,
                confidence=confidence,
                source=payload.source,
                creation_reason="Explicitly stored via remember tool",
                metadata=payload.metadata,
                embedding_vector=emb.vector,
                embedding_model=emb.model,
                embedding_dimensions=emb.dimensions,
                threshold=settings.dedupe_threshold,
            )
            op_status = "deduplicated"
        else:
            mem, action, _, _ = resolve_conflict_or_store(
                session=session,
                user_id=user_id,
                content=raw_text,
                memory_type=payload.type,
                importance=importance,
                confidence=confidence,
                source=payload.source,
                creation_reason="Explicitly stored via remember tool",
                metadata=payload.metadata,
                embedding_vector=emb.vector,
                embedding_model=emb.model,
                embedding_dimensions=emb.dimensions,
                min_similarity=settings.conflict_min_similarity,
                max_similarity=settings.dedupe_threshold,
                llm=get_extraction_provider(settings),
                llm_model=settings.extraction_model,
                llm_timeout=settings.llm_timeout,
            )
            op_status = "superseded" if action == "superseded" else "created"

        read_mem = to_read_schema(mem, enc_key)

    resp_obj = RememberResponse(
        status=op_status,
        action=action,
        memory=read_mem,
        memories=[read_mem],
        count=1,
        message=f"Memory {action} successfully.",
    )
    if idempotency_key:
        default_idempotency_store.set(
            user_id, idempotency_key, 200, resp_obj.model_dump(mode="json")
        )
    return resp_obj


@router.post(
    "/recall",
    response_model=RecallResponse,
    operation_id="recall",
    summary="Recall relevant memories for a query",
    description=(
        "Retrieve relevant user memories for a query, ranked by multi-factor relevance "
        "(semantic similarity, importance, recency, and access frequency). Returns a structured "
        "list of memories and a pre-formatted, character-budgeted `context` markdown string "
        "ready for system prompt injection."
    ),
)
def recall(
    payload: RecallRequest,
    session: Database,
    embedder: Embedder,
    request: Request,
    api_key: ApiKeyDep = None,
) -> RecallResponse:
    settings = request.app.state.settings
    user_id = _resolve_user_id(payload.user_id, api_key, settings)
    enc_key = settings.encryption_key.get_secret_value() if settings.encryption_key else None

    threshold = (
        payload.min_similarity
        if payload.min_similarity is not None
        else settings.retrieval_min_similarity
    )
    query_emb = embedder.embed(payload.query, kind="query")
    sem_rel = 1.0 - Memory.embedding.cosine_distance(query_emb.vector)

    cand_limit = payload.limit * settings.rank_candidate_multiplier

    with session.begin():
        stmt = (
            select(Memory, sem_rel.label("similarity"))
            .where(
                Memory.user_id == user_id,
                Memory.status == "active",
                Memory.embedding_model == embedder.model_id,
                Memory.embedding_dimensions == embedder.dimensions,
            )
            .order_by(sem_rel.desc())
        )
        if payload.type is not None:
            stmt = stmt.where(Memory.type == payload.type)

        candidates = session.execute(stmt.limit(cand_limit)).all()

        scored_items: list[tuple[Memory, float, float]] = []
        now_utc = datetime.now(UTC)

        for mem, sim in candidates:
            sim_val = float(sim) if sim is not None else 0.0
            if sim_val < threshold:
                continue
            rec = calculate_recency(mem.created_at, now_utc, settings.rank_recency_half_life_days)
            freq = calculate_frequency(mem.access_count, settings.rank_frequency_cap)
            score, _ = calculate_score(
                relevance=sim_val,
                importance=float(mem.importance),
                confidence=float(mem.confidence),
                recency=rec,
                frequency=freq,
                settings=settings,
            )
            scored_items.append((mem, score, sim_val))

        # Sort by total score descending
        scored_items.sort(key=lambda x: x[1], reverse=True)
        top_items = scored_items[: payload.limit]

        # Increment access count
        for mem, _, _ in top_items:
            mem.access_count += 1
            mem.last_accessed_at = now_utc

        result_memories: list[RecallMemoryItem] = []
        for mem, score, sim_val in top_items:
            read_m = to_read_schema(mem, enc_key)
            result_memories.append(
                RecallMemoryItem(
                    id=read_m.id,
                    user_id=read_m.user_id,
                    content=read_m.content,
                    type=read_m.type,
                    importance=read_m.importance,
                    confidence=read_m.confidence,
                    source=read_m.source,
                    version=read_m.version,
                    score=score,
                    similarity=sim_val,
                    metadata=read_m.metadata,
                )
            )

    # Format context string
    context_str = build_context(result_memories, settings.context_max_chars)

    return RecallResponse(
        context=context_str,
        memories=result_memories,
        count=len(result_memories),
        query=payload.query,
    )


@router.post(
    "/forget",
    response_model=ForgetResponse,
    operation_id="forget",
    summary="Delete a memory by ID or search query with confirmation",
    description=(
        "Delete a user memory either by its exact UUID (`memory_id`), or by semantically finding "
        "the best match for a `query`. When searching by query without `confirm=true`, the "
        "endpoint returns the candidate memory awaiting confirmation. Pass `confirm=true` to "
        "confirm permanent deletion."
    ),
)
def forget(
    payload: ForgetRequest,
    session: Database,
    embedder: Embedder,
    request: Request,
    api_key: ApiKeyDep = None,
) -> ForgetResponse:
    settings = request.app.state.settings
    user_id = _resolve_user_id(payload.user_id, api_key, settings)
    enc_key = settings.encryption_key.get_secret_value() if settings.encryption_key else None

    # Validate that either memory_id or query is provided
    if payload.memory_id is None and not (payload.query and payload.query.strip()):
        raise HTTPException(
            status_code=422,
            detail="Either 'memory_id' or 'query' must be provided.",
        )

    # 1. Direct Deletion by ID
    if payload.memory_id is not None:
        with session.begin():
            lock_memory(session, user_id, payload.memory_id)
            current = current_memory(session, user_id, payload.memory_id)
            read_mem = to_read_schema(current, enc_key)
            record_event(
                session=session,
                user_id=user_id,
                memory_id=payload.memory_id,
                memory_version=current.version,
                event_type="deleted",
                reason="Deleted via forget tool",
                source=current.source,
                actor="user",
                detail={},
            )
            session.execute(
                delete(Memory).where(Memory.id == payload.memory_id, Memory.user_id == user_id)
            )
        return ForgetResponse(
            confirmed=True,
            status="deleted",
            deleted_id=str(payload.memory_id),
            deleted_memory=read_mem,
            message=f"Memory {payload.memory_id} deleted successfully.",
        )

    # 2. Semantic Search & Confirmation Flow
    query_str = payload.query.strip()
    query_emb = embedder.embed(query_str, kind="query")
    sem_rel = 1.0 - Memory.embedding.cosine_distance(query_emb.vector)

    with session.begin():
        stmt = (
            select(Memory, sem_rel.label("similarity"))
            .where(
                Memory.user_id == user_id,
                Memory.status == "active",
                Memory.embedding_model == embedder.model_id,
                Memory.embedding_dimensions == embedder.dimensions,
            )
            .order_by(sem_rel.desc())
            .limit(1)
        )
        row = session.execute(stmt).first()
        if not row:
            return ForgetResponse(
                confirmed=False,
                status="not_found",
                message="No matching active memory found to delete.",
            )

        best_match, sim = row
        read_mem = to_read_schema(best_match, enc_key)

        if not payload.confirm:
            return ForgetResponse(
                confirmed=False,
                status="pending_confirmation",
                candidate=read_mem,
                message=(
                    f"Candidate memory found: '{read_mem.content}'. "
                    "Call forget again with confirm=true to permanently delete this memory."
                ),
            )

        # Confirmed deletion
        lock_memory(session, user_id, best_match.id)
        record_event(
            session=session,
            user_id=user_id,
            memory_id=best_match.id,
            memory_version=best_match.version,
            event_type="deleted",
            reason="Deleted via forget tool with semantic confirmation",
            source=best_match.source,
            actor="user",
            detail={
                "matched_query": query_str,
                "similarity": float(sim) if sim is not None else None,
            },
        )
        session.execute(delete(Memory).where(Memory.id == best_match.id, Memory.user_id == user_id))

    return ForgetResponse(
        confirmed=True,
        status="deleted",
        deleted_id=str(best_match.id),
        deleted_memory=read_mem,
        message=f"Memory {best_match.id} ('{read_mem.content}') deleted successfully.",
    )


@router.get(
    "/profile",
    response_model=ProfileResponse,
    operation_id="profile",
    summary="Get compact user profile summary and top active memories",
    description=(
        "Retrieve a compact summary of the user's active memories organized by category "
        "(preferences, profile, goals, skills, facts). Returns a pre-assembled markdown profile "
        "ready for context injection."
    ),
)
def get_profile(
    session: Database,
    request: Request,
    user_id: Annotated[str | None, Query(description="Target user identifier")] = None,
    limit: Annotated[
        int, Query(ge=1, le=100, description="Max memories to include in summary")
    ] = 20,
    api_key: ApiKeyDep = None,
) -> ProfileResponse:
    settings = request.app.state.settings
    resolved_uid = _resolve_user_id(user_id, api_key, settings)
    enc_key = settings.encryption_key.get_secret_value() if settings.encryption_key else None

    with session.begin():
        stmt = (
            select(Memory)
            .where(
                Memory.user_id == resolved_uid,
                Memory.status == "active",
            )
            .order_by(
                Memory.importance.desc(),
                Memory.access_count.desc(),
                Memory.updated_at.desc(),
            )
            .limit(limit)
        )
        memories = session.execute(stmt).scalars().all()
        read_mems = [to_read_schema(m, enc_key) for m in memories]

    # Group by category
    categories: dict[str, list[str]] = {
        "profile": [],
        "preference": [],
        "goal": [],
        "skill": [],
        "fact": [],
        "other": [],
    }
    for m in read_mems:
        cat = m.type if m.type in categories else "other"
        categories[cat].append(m.content)

    # Clean empty categories
    active_categories = {k: v for k, v in categories.items() if v}

    # Build summary
    context_str = build_context(read_mems, settings.context_max_chars)
    if context_str:
        summary_lines = [f"User Profile Summary for '{resolved_uid}':", context_str]
    else:
        summary_lines = [f"No active memories recorded for user '{resolved_uid}'."]
    summary_text = "\n".join(summary_lines)

    return ProfileResponse(
        user_id=resolved_uid,
        summary=summary_text,
        memory_count=len(read_mems),
        categories=active_categories,
        memories=read_mems,
    )
