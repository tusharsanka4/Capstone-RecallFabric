"""OpenAI-compatible chat completion memory proxy."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Annotated, Any

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from recallfabric.context.builder import build_context
from recallfabric.core.config import Settings, get_settings
from recallfabric.db.connection import create_database_engine
from recallfabric.db.models import ApiKey, Memory
from recallfabric.embeddings.service import EmbeddingProvider, LocalEmbeddingProvider
from recallfabric.ranking.scoring import (
    calculate_frequency,
    calculate_recency,
    calculate_score,
)
from recallfabric.security.audit import record_audit_event
from recallfabric.security.auth import hash_api_key
from recallfabric.security.encryption import decrypt_content
from recallfabric.security.rate_limiter import rate_limiter
from recallfabric.services.ingest_service import process_ingest_job_sync

logger = logging.getLogger("recallfabric.proxy")

router = APIRouter(tags=["proxy"])


def _extract_user_query(messages: list[dict[str, Any]]) -> str:
    """Extract prompt text from the last user message for memory retrieval."""
    for msg in reversed(messages):
        if msg.get("role") == "user":
            content = msg.get("content")
            if isinstance(content, str):
                return content.strip()
            if isinstance(content, list):
                parts = []
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "text":
                        parts.append(item.get("text", ""))
                    elif isinstance(item, str):
                        parts.append(item)
                return " ".join(parts).strip()
    return ""


def _inject_context_into_messages(
    messages: list[dict[str, Any]],
    context_str: str,
) -> list[dict[str, Any]]:
    """Inject memory context into the system prompt without mutating caller's original list."""
    if not context_str or not context_str.strip():
        return messages

    copied_messages = [dict(m) for m in messages]
    system_idx = None
    for idx, msg in enumerate(copied_messages):
        if msg.get("role") == "system":
            system_idx = idx
            break

    if system_idx is not None:
        orig = copied_messages[system_idx].get("content", "")
        if isinstance(orig, str):
            copied_messages[system_idx]["content"] = f"{orig}\n\n{context_str}".strip()
        else:
            copied_messages[system_idx]["content"] = f"{context_str}\n\n{orig}".strip()
    else:
        copied_messages.insert(0, {"role": "system", "content": context_str.strip()})

    return copied_messages


def _resilient_recall(
    request: Request,
    user_id: str,
    query: str,
    settings: Settings,
) -> str:
    """Recall ranked memories safely. Failures never raise or block chat completions."""
    if not query or not query.strip():
        return ""

    try:
        engine = getattr(request.app.state, "database_engine", None)
        if engine is None:
            engine = create_database_engine(settings)
        embedder: EmbeddingProvider = getattr(
            request.app.state, "embedding_provider", None
        ) or LocalEmbeddingProvider(settings)

        enc_key = settings.encryption_key.get_secret_value() if settings.encryption_key else None
        threshold = settings.retrieval_min_similarity
        query_emb = embedder.embed(query, kind="query")
        sem_rel = 1.0 - Memory.embedding.cosine_distance(query_emb.vector)
        cand_limit = settings.chat_retrieval_limit * settings.rank_candidate_multiplier

        with Session(engine, expire_on_commit=False) as session:
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
                    .limit(cand_limit)
                )
                candidates = session.execute(stmt).all()
                scored_items = []
                now_utc = datetime.now(UTC)

                for mem, sim in candidates:
                    sim_val = float(sim) if sim is not None else 0.0
                    if sim_val < threshold:
                        continue
                    rec = calculate_recency(
                        mem.created_at, now_utc, settings.rank_recency_half_life_days
                    )
                    freq = calculate_frequency(mem.access_count, settings.rank_frequency_cap)
                    score, _ = calculate_score(
                        relevance=sim_val,
                        importance=float(mem.importance),
                        confidence=float(mem.confidence),
                        recency=rec,
                        frequency=freq,
                        settings=settings,
                    )
                    scored_items.append((mem, score))

                scored_items.sort(key=lambda x: x[1], reverse=True)
                top_items = scored_items[: settings.chat_retrieval_limit]

                for mem, _ in top_items:
                    mem.access_count += 1
                    mem.last_accessed_at = now_utc

                mem_objs = []

                class _MemHolder:
                    def __init__(self, content: str, memory_type: str):
                        self.content = content
                        self.type = memory_type

                for mem, _ in top_items:
                    dec = decrypt_content(mem.content, enc_key) if enc_key else mem.content
                    mem_objs.append(_MemHolder(dec, mem.type))

                return build_context(mem_objs, settings.context_max_chars)
    except Exception as exc:
        logger.warning("Memory recall failed in proxy (continuing without memory): %s", exc)
        return ""


def _resolve_proxy_auth(
    request: Request,
    settings: Settings,
) -> tuple[str, str | None]:
    """Resolve authenticated RecallFabric user_id and upstream API key."""
    rf_key = request.headers.get("x-recallfabric-key")
    upstream_key = (
        request.headers.get("x-upstream-key")
        or request.headers.get("x-openai-key")
        or request.headers.get("x-upstream-api-key")
    )

    auth_header = request.headers.get("authorization")
    raw_auth_token = None
    if auth_header:
        parts = auth_header.strip().split(None, 1)
        if len(parts) == 2 and parts[0].lower() == "bearer":
            raw_auth_token = parts[1].strip()
        elif len(parts) == 1:
            raw_auth_token = parts[0].strip()

    engine = getattr(request.app.state, "database_engine", None)
    if engine is None:
        engine = create_database_engine(settings)

    if settings.auth_enabled:
        # Caller might provide rf_key in X-RecallFabric-Key or in Authorization header
        target_rf_token = rf_key or raw_auth_token
        if not target_rf_token:
            raise HTTPException(status_code=401, detail="Missing RecallFabric API key")

        key_hash = hash_api_key(target_rf_token)
        with Session(engine, expire_on_commit=False) as session:
            db_key = session.scalar(
                select(ApiKey).where(ApiKey.key_hash == key_hash, ApiKey.revoked_at.is_(None))
            )
            if db_key is None:
                record_audit_event(
                    session,
                    "auth_failure",
                    ip_address=request.client.host if request.client else None,
                    detail={"reason": "invalid_or_revoked_key", "path": request.url.path},
                )
                session.commit()
                raise HTTPException(status_code=401, detail="Invalid or revoked API key")

            if not rate_limiter.check_rate_limit(
                db_key.key_hash, settings.rate_limit_rps, settings.rate_limit_burst
            ):
                raise HTTPException(status_code=429, detail="Rate limit exceeded")

            db_key.last_used_at = datetime.now(UTC)
            session.commit()
            user_id = db_key.user_id

        # If X-RecallFabric-Key was used, raw_auth_token can be the upstream key
        if rf_key and raw_auth_token and not upstream_key:
            upstream_key = raw_auth_token

        return user_id, upstream_key

    # Auth disabled (development)
    user_id = (
        request.headers.get("x-recallfabric-user-id")
        or request.headers.get("x-user-id")
        or settings.mcp_user_id
        or "default_user"
    )
    if raw_auth_token and not upstream_key:
        upstream_key = raw_auth_token

    return user_id, upstream_key


def _resolve_upstream_url(request: Request, settings: Settings) -> str:
    """Resolve and validate the upstream OpenAI-compatible URL against the allowlist."""
    custom_url = request.headers.get("x-upstream-url") or request.headers.get("x-upstream-base-url")
    if custom_url and custom_url.strip():
        target = custom_url.strip()
        if not settings.is_upstream_allowed(target):
            raise HTTPException(
                status_code=403,
                detail=f"Upstream URL '{target}' is not permitted by RecallFabric proxy allowlist",
            )
        if not target.endswith("/chat/completions"):
            target = f"{target.rstrip('/')}/chat/completions"
        return target

    default_base = settings.proxy_default_upstream_url.rstrip("/")
    if not default_base.endswith("/chat/completions"):
        return f"{default_base}/chat/completions"
    return default_base


@router.post(
    "/proxy/chat/completions",
    summary="OpenAI-compatible memory proxy",
    description=(
        "Accepts standard chat completion requests, retrieves relevant user memories, "
        "injects them into the system message, and forwards the request to upstream LLM providers. "
        "Streams responses back unchanged and optionally extracts new facts asynchronously."
    ),
)
async def proxy_chat_completions(
    request: Request,
    background_tasks: BackgroundTasks,
    settings: Annotated[Settings, Depends(get_settings)],
) -> Response:
    user_id, upstream_key = _resolve_proxy_auth(request, settings)
    upstream_url = _resolve_upstream_url(request, settings)

    # Resolve fallback upstream API key if none supplied per-request
    resolved_upstream_key = upstream_key
    if not resolved_upstream_key:
        if settings.openai_api_key and settings.openai_api_key.get_secret_value().strip():
            resolved_upstream_key = settings.openai_api_key.get_secret_value()
        elif settings.llm_api_key and settings.llm_api_key.get_secret_value().strip():
            resolved_upstream_key = settings.llm_api_key.get_secret_value()

    try:
        body_bytes = await request.body()
        payload = json.loads(body_bytes.decode("utf-8")) if body_bytes else {}
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON body") from exc

    raw_messages = payload.get("messages", [])
    user_query = _extract_user_query(raw_messages)

    # 1. Resilient Memory Recall (Failures never block completion)
    memory_context = _resilient_recall(request, user_id, user_query, settings)

    # 2. Inject Context into Messages
    augmented_messages = _inject_context_into_messages(raw_messages, memory_context)
    payload["messages"] = augmented_messages

    # 3. Prepare Upstream Request Headers (Credentials never logged)
    fwd_headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    if resolved_upstream_key:
        fwd_headers["Authorization"] = f"Bearer {resolved_upstream_key}"

    is_stream = bool(payload.get("stream"))

    # 4. Handle Streaming Response
    if is_stream:
        client = httpx.AsyncClient(timeout=settings.llm_timeout)

        async def stream_generator() -> AsyncIterator[bytes]:
            collected_chunks: list[str] = []
            try:
                req = client.build_request(
                    "POST",
                    upstream_url,
                    headers=fwd_headers,
                    json=payload,
                )
                upstream_resp = await client.send(req, stream=True)
                if upstream_resp.status_code >= 400:
                    err_body = await upstream_resp.aread()
                    yield err_body
                    return

                async for line in upstream_resp.aiter_lines():
                    if line.strip():
                        yield f"{line}\r\n\r\n".encode()
                        # Accumulate tokens for optional background extraction
                        if line.startswith("data: ") and line.strip() != "data: [DONE]":
                            try:
                                chunk_json = json.loads(line[6:])
                                delta = chunk_json.get("choices", [{}])[0].get("delta", {})
                                if "content" in delta and delta["content"]:
                                    collected_chunks.append(delta["content"])
                            except Exception:
                                pass
            finally:
                await client.aclose()
                # Optional background extraction
                should_extract = (
                    request.headers.get("x-recallfabric-extract", "").lower() == "true"
                    or settings.proxy_extract_by_default
                )
                if should_extract and user_query and collected_chunks:
                    assistant_text = "".join(collected_chunks).strip()
                    transcript = [
                        {"role": "user", "content": user_query},
                        {"role": "assistant", "content": assistant_text},
                    ]
                    background_tasks.add_task(
                        process_ingest_job_sync,
                        job_id=f"proxy_{datetime.now(UTC).timestamp()}",
                        user_id=user_id,
                        transcript=transcript,
                        source="proxy_stream",
                        settings=settings,
                        engine=getattr(request.app.state, "database_engine", None),
                        embedder=getattr(request.app.state, "embedding_provider", None),
                    )

        return StreamingResponse(stream_generator(), media_type="text/event-stream")

    # 5. Handle Non-Streaming Response
    async with httpx.AsyncClient(timeout=settings.llm_timeout) as client:
        try:
            upstream_resp = await client.post(
                upstream_url,
                headers=fwd_headers,
                json=payload,
            )
        except httpx.TimeoutException as exc:
            raise HTTPException(status_code=504, detail="Upstream request timed out") from exc
        except httpx.ConnectError as exc:
            raise HTTPException(status_code=503, detail="Upstream service unavailable") from exc
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Upstream request failed: {exc}") from exc

        if upstream_resp.status_code >= 400:
            return Response(
                content=upstream_resp.content,
                status_code=upstream_resp.status_code,
                media_type="application/json",
            )

        # Optional background extraction from non-streaming response
        should_extract = (
            request.headers.get("x-recallfabric-extract", "").lower() == "true"
            or settings.proxy_extract_by_default
        )
        if should_extract and user_query:
            try:
                resp_json = upstream_resp.json()
                assistant_msg = (
                    resp_json.get("choices", [{}])[0].get("message", {}).get("content", "")
                )
                if assistant_msg:
                    transcript = [
                        {"role": "user", "content": user_query},
                        {"role": "assistant", "content": assistant_msg},
                    ]
                    background_tasks.add_task(
                        process_ingest_job_sync,
                        job_id=f"proxy_{datetime.now(UTC).timestamp()}",
                        user_id=user_id,
                        transcript=transcript,
                        source="proxy",
                        settings=settings,
                        engine=getattr(request.app.state, "database_engine", None),
                        embedder=getattr(request.app.state, "embedding_provider", None),
                    )
            except Exception as exc:
                logger.debug("Failed to queue proxy extraction: %s", exc)

        return Response(
            content=upstream_resp.content,
            status_code=upstream_resp.status_code,
            media_type="application/json",
        )
