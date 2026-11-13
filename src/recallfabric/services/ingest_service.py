"""Asynchronous ingestion service for transcript batch extraction."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from threading import Lock
from typing import Any

from sqlalchemy.orm import Session

from recallfabric.core.config import Settings
from recallfabric.db.connection import create_database_engine
from recallfabric.embeddings.service import EmbeddingProvider, LocalEmbeddingProvider
from recallfabric.extraction.filters import filter_candidate
from recallfabric.extraction.prompt import SYSTEM_PROMPT
from recallfabric.memory_manager.conflicts import resolve_conflict_or_store
from recallfabric.memory_manager.dedupe import (
    acquire_dedupe_lock,
    deduplicate_and_store,
    find_duplicate_memory,
)
from recallfabric.providers import get_extraction_provider
from recallfabric.security.encryption import decrypt_content

logger = logging.getLogger("recallfabric.ingest")


class IngestJobStore:
    """Thread-safe job state tracker for transcript batch ingestion."""

    def __init__(self) -> None:
        self._jobs: dict[str, dict[str, Any]] = {}
        self._lock = Lock()

    def create_job(self, job_id: str, user_id: str, message_count: int) -> dict[str, Any]:
        with self._lock:
            now = datetime.now(UTC).isoformat()
            job = {
                "job_id": job_id,
                "user_id": user_id,
                "status": "pending",
                "message_count": message_count,
                "extracted_count": 0,
                "memories": [],
                "error": None,
                "created_at": now,
                "updated_at": now,
            }
            self._jobs[job_id] = job
            return dict(job)

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return dict(job) if job else None

    def update_job(
        self,
        job_id: str,
        status: str,
        extracted_count: int | None = None,
        memories: list[dict[str, Any]] | None = None,
        error: str | None = None,
    ) -> dict[str, Any] | None:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return None
            job["status"] = status
            job["updated_at"] = datetime.now(UTC).isoformat()
            if extracted_count is not None:
                job["extracted_count"] = extracted_count
            if memories is not None:
                job["memories"] = memories
            if error is not None:
                job["error"] = error
            return dict(job)

    def clear(self) -> None:
        with self._lock:
            self._jobs.clear()


default_ingest_job_store = IngestJobStore()


def process_ingest_job_sync(
    job_id: str,
    user_id: str,
    transcript: list[dict[str, Any]],
    source: str,
    settings: Settings,
    engine: Any = None,
    embedder: EmbeddingProvider | None = None,
    job_store: IngestJobStore | None = None,
) -> None:
    """Process transcript extraction and memory persistence in a background worker."""
    store = job_store or default_ingest_job_store
    store.update_job(job_id, "processing")
    eng = engine or create_database_engine(settings)
    emb = embedder or LocalEmbeddingProvider(settings)

    try:
        # 1. Format transcript
        formatted_turns = []
        for item in transcript:
            role = (
                item.get("role", "user")
                if isinstance(item, dict)
                else getattr(item, "role", "user")
            )
            content = (
                item.get("content", "") if isinstance(item, dict) else getattr(item, "content", "")
            )
            formatted_turns.append(f"{role.upper()}: {content}")
        full_text = "\n".join(formatted_turns)

        # 2. Call extraction provider
        provider = get_extraction_provider(settings)
        user_message = (
            f'Extract all atomic facts from this conversation transcript:\n"""\n{full_text}\n"""'
        )

        result_content = provider.chat(
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            temperature=settings.extraction_temperature,
            json_mode=True,
        )
        data = json.loads(result_content)
        candidates_data = data.get("memories", []) if isinstance(data, dict) else []

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

            reason = str(item.get("creation_reason") or "").strip() or "Batch transcript ingest"
            valid_candidates.append((c_text, m_type, imp, conf, reason))

        created_memories = []
        enc_key = settings.encryption_key.get_secret_value() if settings.encryption_key else None

        if valid_candidates:
            with Session(eng, expire_on_commit=False) as session:
                with session.begin():
                    acquire_dedupe_lock(session, user_id)
                    for c_text, m_type, imp, conf, reason in valid_candidates:
                        vec = emb.embed(c_text)
                        matched, _ = find_duplicate_memory(
                            session=session,
                            user_id=user_id,
                            memory_type=m_type,
                            embedding_vector=vec.vector,
                            embedding_model=vec.model,
                            embedding_dimensions=vec.dimensions,
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
                                source=source,
                                creation_reason=reason,
                                metadata={"ingest_job_id": job_id},
                                embedding_vector=vec.vector,
                                embedding_model=vec.model,
                                embedding_dimensions=vec.dimensions,
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
                                source=source,
                                creation_reason=reason,
                                metadata={"ingest_job_id": job_id},
                                embedding_vector=vec.vector,
                                embedding_model=vec.model,
                                embedding_dimensions=vec.dimensions,
                                min_similarity=settings.conflict_min_similarity,
                                max_similarity=settings.dedupe_threshold,
                                llm=provider,
                                llm_model=settings.extraction_model,
                                llm_timeout=settings.llm_timeout,
                            )
                        decrypted = (
                            decrypt_content(mem.content, enc_key) if enc_key else mem.content
                        )
                        created_memories.append(
                            {
                                "id": str(mem.id),
                                "content": decrypted,
                                "type": mem.type,
                                "importance": mem.importance,
                                "action": action,
                            }
                        )

        store.update_job(
            job_id=job_id,
            status="completed",
            extracted_count=len(created_memories),
            memories=created_memories,
        )
    except Exception as exc:
        logger.error("Ingestion job %s failed: %s", job_id, exc, exc_info=True)
        store.update_job(job_id=job_id, status="failed", error=str(exc))
