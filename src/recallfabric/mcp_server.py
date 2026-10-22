import json
import logging
import os
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from mcp.server.mcpserver import MCPServer
from sqlalchemy import Engine, delete, select
from sqlalchemy.orm import Session

from recallfabric.context.builder import build_context
from recallfabric.core.config import Settings
from recallfabric.db.connection import create_database_engine
from recallfabric.db.models import ApiKey, Memory
from recallfabric.embeddings.service import EmbeddingProvider, LocalEmbeddingProvider
from recallfabric.extraction.filters import filter_candidate
from recallfabric.extraction.prompt import SYSTEM_PROMPT
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
from recallfabric.security.audit import record_audit_event
from recallfabric.security.auth import hash_api_key
from recallfabric.security.encryption import decrypt_content, encrypt_content
from recallfabric.services.memory_service import (
    get_memory_history_service,
    list_memories_service,
)

logger = logging.getLogger("recallfabric.mcp")

# Context variable scoping remote HTTP requests to the authenticated user ID
current_mcp_user_id: ContextVar[str] = ContextVar("current_mcp_user_id", default="")


def get_authenticated_user_id(session: Session, settings: Settings) -> str:
    """Resolve authenticated user ID from context, environment, or active API key."""
    ctx_uid = current_mcp_user_id.get()
    if ctx_uid and ctx_uid.strip():
        return ctx_uid.strip()

    api_key_str = os.environ.get("RECALLFABRIC_API_KEY")
    env_user_id = os.environ.get("RECALLFABRIC_USER_ID") or settings.mcp_user_id

    if settings.auth_enabled:
        if not api_key_str:
            raise PermissionError(
                "Authentication is enabled but RECALLFABRIC_API_KEY is not configured."
            )
        hashed = hash_api_key(api_key_str)
        key_record = session.scalar(
            select(ApiKey).where(ApiKey.key_hash == hashed, ApiKey.revoked_at.is_(None))
        )
        if key_record is None:
            raise PermissionError("Invalid or revoked API key.")
        if env_user_id and env_user_id != key_record.user_id:
            raise PermissionError(
                f"User ID mismatch: configured {env_user_id} != key owner {key_record.user_id}"
            )
        return key_record.user_id

    if api_key_str:
        hashed = hash_api_key(api_key_str)
        key_record = session.scalar(
            select(ApiKey).where(ApiKey.key_hash == hashed, ApiKey.revoked_at.is_(None))
        )
        if key_record is not None:
            if env_user_id and env_user_id != key_record.user_id:
                raise PermissionError(
                    f"User ID mismatch: configured {env_user_id} != key owner {key_record.user_id}"
                )
            return key_record.user_id

    return env_user_id or "default_user"


class RecallFabricTools:
    """Internal service wrapper providing clean execution of RecallFabric tools for MCP."""

    def __init__(
        self,
        settings: Settings | None = None,
        engine: Engine | None = None,
        embedder: EmbeddingProvider | None = None,
    ):
        self.settings = settings or Settings()
        self._engine = engine
        self._embedder = embedder

    @property
    def engine(self) -> Engine:
        if self._engine is None:
            self._engine = create_database_engine(self.settings)
        return self._engine

    @engine.setter
    def engine(self, value: Engine | None) -> None:
        self._engine = value

    @property
    def embedder(self) -> EmbeddingProvider:
        if self._embedder is None:
            self._embedder = LocalEmbeddingProvider(self.settings)
        return self._embedder

    @embedder.setter
    def embedder(self, value: EmbeddingProvider | None) -> None:
        self._embedder = value

    def _resolve_user(self, session: Session, user_id: str | None = None) -> str:
        ctx_uid = current_mcp_user_id.get()
        if ctx_uid and ctx_uid.strip():
            return ctx_uid.strip()
        if user_id is not None:
            if self.settings.auth_enabled:
                auth_user = get_authenticated_user_id(session, self.settings)
                if auth_user != user_id:
                    raise PermissionError(f"Cannot act as {user_id}; authenticated as {auth_user}")
                return auth_user
            return user_id
        return get_authenticated_user_id(session, self.settings)

    def _audit(
        self, session: Session, user_id: str, tool_name: str, detail: dict[str, Any]
    ) -> None:
        try:
            record_audit_event(
                session,
                "mcp_tool_call",
                user_id=user_id,
                detail={"tool": tool_name, **detail},
            )
        except Exception as exc:
            logger.debug("Failed to record MCP audit event: %s", exc)

    def remember(
        self,
        content: str,
        type: str = "fact",
        importance: float = 0.5,
        extract: bool = False,
        session: Session | None = None,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        """Store a durable memory or extract facts from free text."""
        if session is not None:
            return self._remember_impl(session, content, type, importance, extract, user_id)
        with Session(self.engine, expire_on_commit=False) as sess:
            with sess.begin():
                return self._remember_impl(sess, content, type, importance, extract, user_id)

    def _remember_impl(
        self,
        session: Session,
        content: str,
        type: str,
        importance: float,
        extract: bool,
        user_id: str | None,
    ) -> dict[str, Any]:
        uid = self._resolve_user(session, user_id)
        self._audit(session, uid, "remember", {"extract": extract, "type": type})
        enc_key = (
            self.settings.encryption_key.get_secret_value()
            if self.settings.encryption_key
            else None
        )
        clean_text = content.strip()

        if extract:
            provider = get_extraction_provider(self.settings)
            user_message = (
                f'Extract all atomic facts from this user message:\n"""\n{clean_text}\n"""'
            )
            try:
                result_content = provider.chat(
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": user_message},
                    ],
                    temperature=self.settings.extraction_temperature,
                    json_mode=True,
                )
                data = json.loads(result_content)
            except Exception as exc:
                logger.warning("Extraction provider failure: %s", exc)
                data = {}

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

                is_valid, _ = filter_candidate(c_text, imp, conf, self.settings)
                if not is_valid:
                    continue
                reason = (
                    str(item.get("creation_reason") or "").strip() or "Extracted via MCP remember"
                )
                valid_candidates.append((c_text, m_type, imp, conf, reason))

            created_memories = []
            acquire_dedupe_lock(session, uid)
            for c_text, m_type, imp, conf, reason in valid_candidates:
                emb = self.embedder.embed(c_text)
                matched, _ = find_duplicate_memory(
                    session=session,
                    user_id=uid,
                    memory_type=m_type,
                    embedding_vector=emb.vector,
                    embedding_model=emb.model,
                    embedding_dimensions=emb.dimensions,
                    threshold=self.settings.dedupe_threshold,
                )
                if matched is not None:
                    mem, action, _ = deduplicate_and_store(
                        session=session,
                        user_id=uid,
                        content=c_text,
                        memory_type=m_type,
                        importance=imp,
                        confidence=conf,
                        source="mcp",
                        creation_reason=reason,
                        metadata={},
                        embedding_vector=emb.vector,
                        embedding_model=emb.model,
                        embedding_dimensions=emb.dimensions,
                        threshold=self.settings.dedupe_threshold,
                    )
                else:
                    mem, action, _, _ = resolve_conflict_or_store(
                        session=session,
                        user_id=uid,
                        content=c_text,
                        memory_type=m_type,
                        importance=imp,
                        confidence=conf,
                        source="mcp",
                        creation_reason=reason,
                        metadata={},
                        embedding_vector=emb.vector,
                        embedding_model=emb.model,
                        embedding_dimensions=emb.dimensions,
                        min_similarity=self.settings.conflict_min_similarity,
                        max_similarity=self.settings.dedupe_threshold,
                        llm=provider,
                        llm_model=self.settings.extraction_model,
                        llm_timeout=self.settings.llm_timeout,
                    )
                decrypted = decrypt_content(mem.content, enc_key) if enc_key else mem.content
                created_memories.append(
                    {
                        "id": str(mem.id),
                        "content": decrypted,
                        "type": mem.type,
                        "importance": mem.importance,
                        "action": action,
                    }
                )

            return {
                "status": "extracted",
                "action": "extracted",
                "memories": created_memories,
                "count": len(created_memories),
                "message": f"Extracted and stored {len(created_memories)} memories.",
            }

        # Direct memory storage
        emb = self.embedder.embed(clean_text)
        acquire_dedupe_lock(session, uid)
        matched, _ = find_duplicate_memory(
            session=session,
            user_id=uid,
            memory_type=type,
            embedding_vector=emb.vector,
            embedding_model=emb.model,
            embedding_dimensions=emb.dimensions,
            threshold=self.settings.dedupe_threshold,
        )
        if matched is not None:
            mem, action, _ = deduplicate_and_store(
                session=session,
                user_id=uid,
                content=clean_text,
                memory_type=type,
                importance=importance,
                confidence=1.0,
                source="mcp",
                creation_reason="Explicitly stored via MCP remember tool",
                metadata={},
                embedding_vector=emb.vector,
                embedding_model=emb.model,
                embedding_dimensions=emb.dimensions,
                threshold=self.settings.dedupe_threshold,
            )
            op_status = "deduplicated"
        else:
            mem, action, _, _ = resolve_conflict_or_store(
                session=session,
                user_id=uid,
                content=clean_text,
                memory_type=type,
                importance=importance,
                confidence=1.0,
                source="mcp",
                creation_reason="Explicitly stored via MCP remember tool",
                metadata={},
                embedding_vector=emb.vector,
                embedding_model=emb.model,
                embedding_dimensions=emb.dimensions,
                min_similarity=self.settings.conflict_min_similarity,
                max_similarity=self.settings.dedupe_threshold,
                llm=get_extraction_provider(self.settings),
                llm_model=self.settings.extraction_model,
                llm_timeout=self.settings.llm_timeout,
            )
            op_status = "superseded" if action == "superseded" else "created"

        decrypted = decrypt_content(mem.content, enc_key) if enc_key else mem.content
        mem_dict = {
            "id": str(mem.id),
            "content": decrypted,
            "type": mem.type,
            "importance": mem.importance,
            "version": mem.version,
            "action": action,
        }
        return {
            "status": op_status,
            "action": action,
            "memory": mem_dict,
            "memories": [mem_dict],
            "count": 1,
            "message": f"Memory {action} successfully.",
        }

    def recall(
        self,
        query: str,
        limit: int = 5,
        type: str | None = None,
        session: Session | None = None,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        """Recall relevant user memories for a query, formatted with context."""
        if session is not None:
            return self._recall_impl(session, query, limit, type, user_id)
        with Session(self.engine, expire_on_commit=False) as sess:
            with sess.begin():
                return self._recall_impl(sess, query, limit, type, user_id)

    def _recall_impl(
        self,
        session: Session,
        query: str,
        limit: int,
        type: str | None,
        user_id: str | None,
    ) -> dict[str, Any]:
        uid = self._resolve_user(session, user_id)
        self._audit(session, uid, "recall", {"query": query, "limit": limit, "type": type})
        enc_key = (
            self.settings.encryption_key.get_secret_value()
            if self.settings.encryption_key
            else None
        )

        threshold = self.settings.retrieval_min_similarity
        query_emb = self.embedder.embed(query, kind="query")
        sem_rel = 1.0 - Memory.embedding.cosine_distance(query_emb.vector)
        cand_limit = limit * self.settings.rank_candidate_multiplier

        stmt = (
            select(Memory, sem_rel.label("similarity"))
            .where(
                Memory.user_id == uid,
                Memory.status == "active",
                Memory.embedding_model == self.embedder.model_id,
                Memory.embedding_dimensions == self.embedder.dimensions,
            )
            .order_by(sem_rel.desc())
        )
        if type is not None:
            stmt = stmt.where(Memory.type == type)

        candidates = session.execute(stmt.limit(cand_limit)).all()
        scored_items = []
        now_utc = datetime.now(UTC)

        for mem, sim in candidates:
            sim_val = float(sim) if sim is not None else 0.0
            if sim_val < threshold:
                continue
            rec = calculate_recency(
                mem.created_at, now_utc, self.settings.rank_recency_half_life_days
            )
            freq = calculate_frequency(mem.access_count, self.settings.rank_frequency_cap)
            score, _ = calculate_score(
                relevance=sim_val,
                importance=float(mem.importance),
                confidence=float(mem.confidence),
                recency=rec,
                frequency=freq,
                settings=self.settings,
            )
            scored_items.append((mem, score, sim_val))

        scored_items.sort(key=lambda x: x[1], reverse=True)
        top_items = scored_items[:limit]

        for mem, _, _ in top_items:
            mem.access_count += 1
            mem.last_accessed_at = now_utc

        result_memories = []
        mem_objs_for_context = []
        for mem, score, sim_val in top_items:
            decrypted = decrypt_content(mem.content, enc_key) if enc_key else mem.content
            item = {
                "id": str(mem.id),
                "content": decrypted,
                "type": mem.type,
                "importance": mem.importance,
                "version": mem.version,
                "score": round(score, 4),
                "similarity": round(sim_val, 4),
            }
            result_memories.append(item)

            class _MemObj:
                def __init__(self, content: str, memory_type: str):
                    self.content = content
                    self.type = memory_type

            mem_objs_for_context.append(_MemObj(decrypted, mem.type))

        context_str = build_context(mem_objs_for_context, self.settings.context_max_chars)
        return {
            "context": context_str,
            "memories": result_memories,
            "count": len(result_memories),
            "query": query,
        }

    def forget(
        self,
        memory_id: str | None = None,
        query: str | None = None,
        confirm: bool = False,
        session: Session | None = None,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        """Delete an existing memory by ID or search query with confirmation."""
        if session is not None:
            return self._forget_impl(session, memory_id, query, confirm, user_id)
        with Session(self.engine, expire_on_commit=False) as sess:
            with sess.begin():
                return self._forget_impl(sess, memory_id, query, confirm, user_id)

    def _forget_impl(
        self,
        session: Session,
        memory_id: str | None,
        query: str | None,
        confirm: bool,
        user_id: str | None,
    ) -> dict[str, Any]:
        uid = self._resolve_user(session, user_id)
        self._audit(
            session, uid, "forget", {"memory_id": memory_id, "query": query, "confirm": confirm}
        )
        enc_key = (
            self.settings.encryption_key.get_secret_value()
            if self.settings.encryption_key
            else None
        )

        if memory_id is not None:
            try:
                target_uuid = UUID(str(memory_id))
            except ValueError:
                return {
                    "confirmed": False,
                    "status": "error",
                    "message": f"Invalid UUID format: {memory_id}",
                }
            mem = session.scalar(
                select(Memory).where(Memory.id == target_uuid, Memory.user_id == uid)
            )
            if mem is None:
                return {
                    "confirmed": False,
                    "status": "not_found",
                    "message": f"Memory {memory_id} not found.",
                }
            decrypted = decrypt_content(mem.content, enc_key) if enc_key else mem.content
            record_event(
                session=session,
                user_id=uid,
                memory_id=mem.id,
                memory_version=mem.version,
                event_type="deleted",
                reason="Deleted via MCP forget tool",
                source=mem.source,
                actor="user",
                detail={},
            )
            session.execute(delete(Memory).where(Memory.id == mem.id, Memory.user_id == uid))
            return {
                "confirmed": True,
                "status": "deleted",
                "deleted_id": str(mem.id),
                "deleted_memory": {"id": str(mem.id), "content": decrypted, "type": mem.type},
                "message": f"Memory {mem.id} deleted successfully.",
            }

        if query and query.strip():
            query_str = query.strip()
            query_emb = self.embedder.embed(query_str, kind="query")
            sem_rel = 1.0 - Memory.embedding.cosine_distance(query_emb.vector)
            stmt = (
                select(Memory, sem_rel.label("similarity"))
                .where(
                    Memory.user_id == uid,
                    Memory.status == "active",
                    Memory.embedding_model == self.embedder.model_id,
                    Memory.embedding_dimensions == self.embedder.dimensions,
                )
                .order_by(sem_rel.desc())
                .limit(1)
            )
            row = session.execute(stmt).first()
            if not row:
                return {
                    "confirmed": False,
                    "status": "not_found",
                    "message": "No matching active memory found to delete.",
                }

            best_match, sim = row
            decrypted = (
                decrypt_content(best_match.content, enc_key) if enc_key else best_match.content
            )
            cand = {
                "id": str(best_match.id),
                "content": decrypted,
                "type": best_match.type,
                "similarity": round(float(sim), 4) if sim is not None else 0.0,
            }

            if not confirm:
                return {
                    "confirmed": False,
                    "status": "pending_confirmation",
                    "candidate": cand,
                    "message": (
                        f"Candidate memory found: '{decrypted}'. "
                        "Call forget again with confirm=true to permanently delete this memory."
                    ),
                }

            # Confirmed deletion
            record_event(
                session=session,
                user_id=uid,
                memory_id=best_match.id,
                memory_version=best_match.version,
                event_type="deleted",
                reason="Deleted via MCP forget tool with semantic confirmation",
                source=best_match.source,
                actor="user",
                detail={
                    "matched_query": query_str,
                    "similarity": float(sim) if sim is not None else None,
                },
            )
            session.execute(delete(Memory).where(Memory.id == best_match.id, Memory.user_id == uid))
            return {
                "confirmed": True,
                "status": "deleted",
                "deleted_id": str(best_match.id),
                "deleted_memory": cand,
                "message": f"Memory {best_match.id} ('{decrypted}') deleted successfully.",
            }

        return {
            "confirmed": False,
            "status": "error",
            "message": "Either 'memory_id' or 'query' must be provided.",
        }

    def list_memories(
        self,
        type: str | None = None,
        status: str = "active",
        limit: int = 50,
        session: Session | None = None,
        user_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """List active stored memories for the user."""
        if session is not None:
            return self._list_memories_impl(session, type, status, limit, user_id)
        with Session(self.engine, expire_on_commit=False) as sess:
            with sess.begin():
                return self._list_memories_impl(sess, type, status, limit, user_id)

    def _list_memories_impl(
        self,
        session: Session,
        type: str | None,
        status: str,
        limit: int,
        user_id: str | None,
    ) -> list[dict[str, Any]]:
        uid = self._resolve_user(session, user_id)
        self._audit(session, uid, "list_memories", {"type": type, "status": status, "limit": limit})
        return list_memories_service(
            session=session,
            settings=self.settings,
            user_id=uid,
            type=type,
            status=status,
            limit=limit,
        )

    def update_memory(
        self,
        id: str,
        content: str | None = None,
        type: str | None = None,
        importance: float | None = None,
        expected_version: int | None = None,
        session: Session | None = None,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        """Update an existing memory's content, category, or importance rating."""
        if session is not None:
            return self._update_memory_impl(
                session, id, content, type, importance, expected_version, user_id
            )
        with Session(self.engine, expire_on_commit=False) as sess:
            with sess.begin():
                return self._update_memory_impl(
                    sess, id, content, type, importance, expected_version, user_id
                )

    def _update_memory_impl(
        self,
        session: Session,
        id: str,
        content: str | None,
        type: str | None,
        importance: float | None,
        expected_version: int | None,
        user_id: str | None,
    ) -> dict[str, Any]:
        uid = self._resolve_user(session, user_id)
        self._audit(
            session,
            uid,
            "update_memory",
            {"id": id, "type": type, "has_content": content is not None},
        )
        enc_key = (
            self.settings.encryption_key.get_secret_value()
            if self.settings.encryption_key
            else None
        )

        target_uuid = UUID(str(id))
        previous = session.scalar(
            select(Memory).where(
                Memory.id == target_uuid,
                Memory.user_id == uid,
                Memory.status.in_(["active", "disabled"]),
            )
        )
        if previous is None:
            raise ValueError(f"Memory {id} not found.")

        if expected_version is not None and previous.version != expected_version:
            raise ValueError(
                f"Version mismatch: expected {expected_version}, current {previous.version}"
            )

        decrypted_prev = decrypt_content(previous.content, enc_key) if enc_key else previous.content
        new_content = content.strip() if content and content.strip() else decrypted_prev
        new_type = type if type is not None else previous.type
        new_importance = importance if importance is not None else previous.importance

        reusable = (
            new_content == decrypted_prev
            and previous.embedding is not None
            and previous.embedding_model == self.embedder.model_id
            and previous.embedding_dimensions == self.embedder.dimensions
        )
        cached = (
            (list(previous.embedding), previous.embedding_model, previous.embedding_dimensions)
            if reusable
            else None
        )
        embedding = None if reusable else self.embedder.embed(new_content)

        stored_content = encrypt_content(new_content, enc_key) if enc_key else new_content
        previous.status = "superseded"
        session.flush()

        new_mem = Memory(
            id=previous.id,
            user_id=uid,
            content=stored_content,
            type=new_type,
            importance=new_importance,
            confidence=previous.confidence,
            source="mcp",
            version=previous.version + 1,
            previous_version=previous.version,
            status="active",
            creation_reason="Updated via MCP update_memory tool",
            attributes=previous.attributes or {},
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
            user_id=uid,
            memory_id=new_mem.id,
            memory_version=new_mem.version,
            event_type="superseded",
            reason="Updated via MCP update_memory tool",
            source="mcp",
            actor="user",
            detail={"confidence": new_mem.confidence},
        )

        return {
            "id": str(new_mem.id),
            "content": new_content,
            "type": new_mem.type,
            "importance": new_mem.importance,
            "version": new_mem.version,
            "status": new_mem.status,
            "updated_at": new_mem.updated_at.isoformat() if new_mem.updated_at else None,
        }

    def get_memory_history(
        self,
        id: str,
        session: Session | None = None,
        user_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Retrieve revision audit trail and provenance for a specific memory."""
        if session is not None:
            return self._get_memory_history_impl(session, id, user_id)
        with Session(self.engine, expire_on_commit=False) as sess:
            with sess.begin():
                return self._get_memory_history_impl(sess, id, user_id)

    def _get_memory_history_impl(
        self,
        session: Session,
        id: str,
        user_id: str | None,
    ) -> list[dict[str, Any]]:
        uid = self._resolve_user(session, user_id)
        self._audit(session, uid, "get_memory_history", {"id": id})
        return get_memory_history_service(
            session=session,
            settings=self.settings,
            user_id=uid,
            memory_id=id,
        )

    def get_profile(
        self,
        limit: int = 20,
        session: Session | None = None,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        """Retrieve structured user profile summary and top active memories."""
        if session is not None:
            return self._get_profile_impl(session, limit, user_id)
        with Session(self.engine, expire_on_commit=False) as sess:
            with sess.begin():
                return self._get_profile_impl(sess, limit, user_id)

    def _get_profile_impl(
        self,
        session: Session,
        limit: int,
        user_id: str | None,
    ) -> dict[str, Any]:
        uid = self._resolve_user(session, user_id)
        self._audit(session, uid, "get_profile", {"limit": limit})
        enc_key = (
            self.settings.encryption_key.get_secret_value()
            if self.settings.encryption_key
            else None
        )

        stmt = (
            select(Memory)
            .where(Memory.user_id == uid, Memory.status == "active")
            .order_by(
                Memory.importance.desc(), Memory.access_count.desc(), Memory.updated_at.desc()
            )
            .limit(limit)
        )
        memories = session.execute(stmt).scalars().all()

        categories: dict[str, list[str]] = {
            "profile": [],
            "preference": [],
            "goal": [],
            "skill": [],
            "fact": [],
            "other": [],
        }
        read_mems = []
        mem_objs_for_context = []

        class _MemObj:
            def __init__(self, content: str, memory_type: str):
                self.content = content
                self.type = memory_type

        for m in memories:
            decrypted = decrypt_content(m.content, enc_key) if enc_key else m.content
            cat = m.type if m.type in categories else "other"
            categories[cat].append(decrypted)
            read_mems.append(
                {
                    "id": str(m.id),
                    "content": decrypted,
                    "type": m.type,
                    "importance": m.importance,
                }
            )
            mem_objs_for_context.append(_MemObj(decrypted, m.type))

        active_cats = {k: v for k, v in categories.items() if v}
        context_str = build_context(mem_objs_for_context, self.settings.context_max_chars)
        if context_str:
            summary = f"User Profile Summary for '{uid}':\n{context_str}"
        else:
            summary = f"No active memories recorded for user '{uid}'."

        return {
            "user_id": uid,
            "summary": summary,
            "memory_count": len(read_mems),
            "categories": active_cats,
            "memories": read_mems,
        }

    # Backward compatibility wrappers for M15 test suite
    def store_memory(
        self,
        content: str,
        type: str = "fact",
        importance: float = 0.5,
        confidence: float = 1.0,
        source: str = "mcp",
        session: Session | None = None,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        res = self.remember(
            content=content,
            type=type,
            importance=importance,
            extract=False,
            session=session,
            user_id=user_id,
        )
        mem = res.get("memory") or (res["memories"][0] if res.get("memories") else {})
        return {
            "id": mem.get("id"),
            "content": mem.get("content", content),
            "type": mem.get("type", type),
            "version": mem.get("version", 1),
            "user_id": user_id or self._resolve_user(session or Session(self.engine)),
            **res,
        }

    def search_memory(
        self,
        query: str,
        limit: int = 20,
        type: str | None = None,
        session: Session | None = None,
        user_id: str | None = None,
    ) -> list[dict[str, Any]]:
        rec = self.recall(query=query, limit=limit, type=type, session=session, user_id=user_id)
        return rec.get("memories", [])

    def delete_memory(
        self,
        id: str,
        session: Session | None = None,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        res = self.forget(memory_id=id, confirm=True, session=session, user_id=user_id)
        return {"deleted": res.get("status") == "deleted", **res}


def create_mcp_server(
    settings: Settings | None = None,
    engine: Engine | None = None,
    embedder: EmbeddingProvider | None = None,
    tools: RecallFabricTools | None = None,
) -> MCPServer:
    """Create and configure the RecallFabric MCP Server with tools, resources, and prompts."""
    settings = settings or Settings()
    active_tools = tools or RecallFabricTools(settings=settings, engine=engine, embedder=embedder)
    server = MCPServer("recallfabric")

    # 1. Primary AI Memory Tools (Never accept user_id in signature)
    @server.tool(
        description=(
            "Store a durable memory or extract facts from conversation. "
            "Call remember whenever the user expresses a durable preference, fact, goal, "
            "constraint, or personal detail that should persist across future conversations. "
            "If the user provides a conversational paragraph with multiple facts, set "
            "extract=true to automatically isolate and store each individual memory statement. "
            "Do NOT pass user_id."
        )
    )
    def remember(
        content: str,
        type: str = "fact",
        importance: float = 0.5,
        extract: bool = False,
    ) -> dict[str, Any]:
        """Store a durable memory or extract atomic facts from text."""
        return active_tools.remember(
            content=content, type=type, importance=importance, extract=extract
        )

    @server.tool(
        description=(
            "Recall relevant user memories for a query. "
            "Call recall at the beginning of a conversation, when the user asks a question "
            "that might depend on past context, or before giving personalized recommendations. "
            "Returns ranked memory items and a pre-formatted 'context' string ready for use. "
            "Do NOT pass user_id."
        )
    )
    def recall(
        query: str,
        limit: int = 5,
        type: str | None = None,
    ) -> dict[str, Any]:
        """Recall relevant user memories for a query, formatted with context."""
        return active_tools.recall(query=query, limit=limit, type=type)

    @server.tool(
        description=(
            "Delete or remove an existing memory. "
            "Call forget when the user explicitly requests to forget, delete, or remove "
            "stored information. You can specify a memory_id directly, or provide a query string "
            "to find and confirm candidate memories to erase. When searching by query without "
            "confirm=true, a candidate memory is returned for confirmation before deletion. "
            "Do NOT pass user_id."
        )
    )
    def forget(
        memory_id: str | None = None,
        query: str | None = None,
        confirm: bool = False,
    ) -> dict[str, Any]:
        """Delete an existing memory by ID or semantic query with confirmation."""
        return active_tools.forget(memory_id=memory_id, query=query, confirm=confirm)

    @server.tool(
        description=(
            "List stored memories for the user. "
            "Call list_memories when the user asks what you know about them, wants to review "
            "their preferences, or when you need a full inventory of memories under a specific "
            "category (e.g. 'preference', 'goal', 'skill', 'profile', 'fact'). "
            "Do NOT pass user_id."
        )
    )
    def list_memories(
        type: str | None = None,
        status: str = "active",
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """List active stored memories for the user."""
        return active_tools.list_memories(type=type, status=status, limit=limit)

    @server.tool(
        description=(
            "Update an existing memory by ID. "
            "Call update_memory when the user modifies, refines, or corrects a specific "
            "prior preference, fact, or attribute. "
            "Do NOT pass user_id."
        )
    )
    def update_memory(
        id: str,
        content: str | None = None,
        type: str | None = None,
        importance: float | None = None,
        expected_version: int | None = None,
    ) -> dict[str, Any]:
        """Update an existing memory's content, category, or importance rating."""
        return active_tools.update_memory(
            id=id,
            content=content,
            type=type,
            importance=importance,
            expected_version=expected_version,
        )

    @server.tool(
        description=(
            "Retrieve the audit history and revision provenance for a specific memory by ID. "
            "Call get_memory_history when the user inquires about how or when a specific memory "
            "was created, updated, or superseded. "
            "Do NOT pass user_id."
        )
    )
    def get_memory_history(id: str) -> list[dict[str, Any]]:
        """Retrieve the revision history and provenance audit trail for a memory."""
        return active_tools.get_memory_history(id=id)

    @server.tool(
        description=(
            "Get a high-level structured profile summary of the user. "
            "Call get_profile at the start of a conversation to quickly understand the user's "
            "key active preferences, goals, background, and constraints in a single structured "
            "overview. Do NOT pass user_id."
        )
    )
    def get_profile(limit: int = 20) -> dict[str, Any]:
        """Retrieve a high-level profile summary and top active memories grouped by category."""
        return active_tools.get_profile(limit=limit)

    # 2. Backward Compatibility Aliases for M15 test suite
    @server.tool(description="Legacy alias for recall tool")
    def search_memory(
        query: str,
        limit: int = 20,
        type: str | None = None,
    ) -> list[dict[str, Any]]:
        return active_tools.search_memory(query=query, limit=limit, type=type)

    @server.tool(description="Legacy alias for remember tool")
    def store_memory(
        content: str,
        type: str = "fact",
        importance: float = 0.5,
        confidence: float = 1.0,
        source: str = "mcp",
    ) -> dict[str, Any]:
        return active_tools.store_memory(
            content=content,
            type=type,
            importance=importance,
            confidence=confidence,
            source=source,
        )

    @server.tool(description="Legacy alias for forget tool")
    def delete_memory(id: str) -> dict[str, Any]:
        return active_tools.delete_memory(id=id)

    # 3. MCP Resources
    @server.resource(
        "memory://profile",
        name="memory_profile",
        description="Active user profile summary and top memories by category.",
    )
    def get_memory_profile_resource() -> str:
        """Read the active user memory profile."""
        profile = active_tools.get_profile()
        return profile.get("summary", "")

    # 4. MCP Prompts
    @server.prompt(
        "use_memory",
        description="Guidance and instructions for how and when the LLM should use memory tools.",
    )
    def use_memory_prompt() -> str:
        """System prompt instructions for effective memory tool usage."""
        return (
            "You are equipped with RecallFabric, a long-term memory engine. "
            "Use the memory tools to maintain continuity across interactions:\n"
            "1. At the beginning of a conversation, or before answering user-specific queries, "
            "call `recall` with a relevant search query, or inspect `memory://profile`.\n"
            "2. When the user mentions durable facts, preferences, constraints, or goals, "
            "call `remember` to persist them.\n"
            "3. If a user message contains multiple distinct facts, "
            "call `remember` with `extract=true` to extract each fact automatically.\n"
            "4. When information changes or is corrected, call `update_memory`.\n"
            "5. If the user asks to forget, erase, or delete information, call `forget`.\n"
            "6. To see an overview of active memory categories, call `get_profile`.\n"
            "Never specify a user_id parameter; the server automatically maps your "
            "authenticated session to the user."
        )

    server.tools_wrapper = active_tools
    return server


def main() -> None:
    settings = Settings()
    server = create_mcp_server(settings)
    if settings.mcp_transport == "streamable-http":
        server.run("streamable-http", host=settings.mcp_host, port=settings.mcp_port)
    elif settings.mcp_transport == "sse":
        server.run("sse", host=settings.mcp_host, port=settings.mcp_port)
    else:
        server.run("stdio")


if __name__ == "__main__":
    main()
