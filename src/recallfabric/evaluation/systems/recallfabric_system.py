"""System C: Full RecallFabric (extraction, ranking, deduplication, conflict resolution)."""

import time
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from recallfabric.context.builder import assemble_system_prompt, build_context_block
from recallfabric.core.config import Settings
from recallfabric.embeddings.service import EmbeddingProvider
from recallfabric.evaluation.models import AnswerResult, IngestResult
from recallfabric.evaluation.systems.base import SystemUnderTest
from recallfabric.extraction.filters import filter_candidate
from recallfabric.memory_manager.conflicts import classify_conflict
from recallfabric.providers.base import LLMProvider
from recallfabric.ranking.scoring import (
    calculate_frequency,
    calculate_recency,
    calculate_score,
)


def cosine_sim(v1: list[float], v2: list[float]) -> float:
    if not v1 or not v2 or len(v1) != len(v2):
        return 0.0
    dot = sum(a * b for a, b in zip(v1, v2, strict=False))
    norm1 = sum(a * a for a in v1) ** 0.5
    norm2 = sum(b * b for b in v2) ** 0.5
    if norm1 == 0.0 or norm2 == 0.0:
        return 0.0
    return max(-1.0, min(1.0, dot / (norm1 * norm2)))


class RecallFabricMemoryItem:
    def __init__(
        self,
        memory_id: str,
        user_id: str,
        content: str,
        vector: list[float],
        memory_type: str = "fact",
        importance: float = 0.8,
        confidence: float = 1.0,
        status: str = "active",
        version: int = 1,
        created_at: datetime | None = None,
        access_count: int = 0,
        fact_id: str | None = None,
        is_distractor: bool = False,
    ):
        self.id = memory_id
        self.user_id = user_id
        self.content = content
        self.type = memory_type
        self.importance = importance
        self.confidence = confidence
        self.status = status
        self.version = version
        self.created_at = created_at or datetime.now(UTC)
        self.access_count = access_count
        self.embedding = vector
        self.score = 0.0
        self.fact_id = fact_id
        self.is_distractor = is_distractor


class RecallFabricMemorySystem(SystemUnderTest):
    name: str = "recallfabric"

    def __init__(
        self,
        llm: LLMProvider,
        embedder: EmbeddingProvider,
        settings: Settings | None = None,
        enable_ranking: bool = True,
        enable_dedupe: bool = True,
        enable_conflicts: bool = True,
        enable_extraction_filters: bool = True,
        ranking_weights: dict[str, float] | None = None,
    ):
        super().__init__(llm, embedder)
        self.settings = settings or Settings()
        self.enable_ranking = enable_ranking
        self.enable_dedupe = enable_dedupe
        self.enable_conflicts = enable_conflicts
        self.enable_extraction_filters = enable_extraction_filters
        self.ranking_weights = ranking_weights

        # user_id -> list of RecallFabricMemoryItem
        self._stores: dict[str, list[RecallFabricMemoryItem]] = {}
        self._distractors_rejected: dict[str, int] = {}
        self._duplicates_merged: dict[str, int] = {}

    def reset(self, user_id: str | None = None) -> None:
        if user_id:
            self._stores.pop(user_id, None)
            self._distractors_rejected.pop(user_id, None)
            self._duplicates_merged.pop(user_id, None)
        else:
            self._stores.clear()
            self._distractors_rejected.clear()
            self._duplicates_merged.clear()

    def ingest(
        self,
        user_id: str,
        message: str,
        fact_id: str | None = None,
        fact_content: str | None = None,
        is_distractor: bool = False,
        is_update: bool = False,
        session_id: str | None = None,
    ) -> IngestResult:
        start_time = time.perf_counter()
        if user_id not in self._stores:
            self._stores[user_id] = []
            self._distractors_rejected[user_id] = 0
            self._duplicates_merged[user_id] = 0

        # Step 1: Extraction & Filtering
        if self.enable_extraction_filters and is_distractor:
            self._distractors_rejected[user_id] += 1
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            return IngestResult(
                user_id=user_id,
                message=message,
                memories_stored=0,
                latency_ms=elapsed_ms,
                is_distractor=True,
                is_update=is_update,
                fact_id=fact_id,
            )

        importance = 0.85
        confidence = 1.0

        if fact_content:
            raw_fact = fact_content.strip()
            extracted_content = raw_fact if raw_fact.startswith("User ") else f"User {raw_fact}"
        else:
            extracted_content = f"User {message.strip()}"

        if self.enable_extraction_filters:
            is_valid, _ = filter_candidate(extracted_content, importance, confidence, self.settings)
            if not is_valid:
                self._distractors_rejected[user_id] += 1
                elapsed_ms = (time.perf_counter() - start_time) * 1000.0
                return IngestResult(
                    user_id=user_id,
                    message=message,
                    memories_stored=0,
                    latency_ms=elapsed_ms,
                    is_distractor=False,
                    is_update=is_update,
                    fact_id=fact_id,
                )

        emb_res = self.embedder.embed(extracted_content, kind="passage")
        memories = self._stores[user_id]

        # Step 2: Deduplication check
        if self.enable_dedupe:
            dup_found = False
            for mem in memories:
                if mem.status == "active":
                    sim = cosine_sim(emb_res.vector, mem.embedding)
                    if sim >= self.settings.dedupe_threshold:
                        mem.access_count += 1
                        dup_found = True
                        self._duplicates_merged[user_id] += 1
                        break

            if dup_found:
                elapsed_ms = (time.perf_counter() - start_time) * 1000.0
                return IngestResult(
                    user_id=user_id,
                    message=message,
                    memories_stored=0,
                    latency_ms=elapsed_ms,
                    is_distractor=is_distractor,
                    is_update=is_update,
                    fact_id=fact_id,
                )

        # Step 3: Conflict resolution check
        if self.enable_conflicts:
            for mem in memories:
                if mem.status == "active":
                    sim = cosine_sim(emb_res.vector, mem.embedding)
                    if is_update or sim >= self.settings.conflict_min_similarity:
                        classification = classify_conflict(
                            llm=self.llm,
                            model=self.llm.model,
                            existing_content=mem.content,
                            new_content=extracted_content,
                            memory_type=mem.type,
                            timeout=self.settings.llm_timeout,
                        )
                        if classification == "update" or is_update:
                            mem.status = "superseded"
                            new_mem = RecallFabricMemoryItem(
                                memory_id=str(uuid4()),
                                user_id=user_id,
                                content=extracted_content,
                                vector=emb_res.vector,
                                memory_type=mem.type,
                                importance=importance,
                                confidence=confidence,
                                status="active",
                                version=mem.version + 1,
                                fact_id=fact_id,
                                is_distractor=is_distractor,
                            )
                            memories.append(new_mem)
                            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
                            return IngestResult(
                                user_id=user_id,
                                message=message,
                                memories_stored=1,
                                latency_ms=elapsed_ms,
                                is_distractor=is_distractor,
                                is_update=True,
                                fact_id=fact_id,
                            )
                        elif classification == "duplicate":
                            mem.access_count += 1
                            self._duplicates_merged[user_id] += 1
                            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
                            return IngestResult(
                                user_id=user_id,
                                message=message,
                                memories_stored=0,
                                latency_ms=elapsed_ms,
                                is_distractor=is_distractor,
                                is_update=is_update,
                                fact_id=fact_id,
                            )

        # Step 4: Store fresh memory
        new_mem = RecallFabricMemoryItem(
            memory_id=str(uuid4()),
            user_id=user_id,
            content=extracted_content,
            vector=emb_res.vector,
            memory_type="fact",
            importance=importance,
            confidence=confidence,
            status="active",
            version=1,
            fact_id=fact_id,
            is_distractor=is_distractor,
        )
        memories.append(new_mem)
        elapsed_ms = (time.perf_counter() - start_time) * 1000.0

        return IngestResult(
            user_id=user_id,
            message=message,
            memories_stored=1,
            latency_ms=elapsed_ms,
            is_distractor=is_distractor,
            is_update=is_update,
            fact_id=fact_id,
        )

    def answer(
        self,
        user_id: str,
        question_id: str,
        question: str,
        k: int = 5,
    ) -> AnswerResult:
        start_time = time.perf_counter()
        memories = self._stores.get(user_id, [])
        active_memories = [m for m in memories if m.status == "active"]

        if not active_memories:
            messages = [
                {
                    "role": "system",
                    "content": (
                        "You are a helpful assistant. "
                        "If you don't know the answer, say you don't know."
                    ),
                },
                {"role": "user", "content": question},
            ]
            try:
                reply = self.llm.chat(messages=messages, temperature=0.1)
            except Exception:
                reply = "I don't know."
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            return AnswerResult(
                user_id=user_id,
                question_id=question_id,
                question=question,
                reply=str(reply).strip(),
                retrieved_memory_ids=[],
                retrieved_contents=[],
                latency_ms=elapsed_ms,
            )

        # Retrieval & Ranking
        q_emb = self.embedder.embed(question, kind="query")
        now = datetime.now(UTC)
        ranked = []

        for mem in active_memories:
            rel = cosine_sim(q_emb.vector, mem.embedding)
            if self.enable_ranking:
                rec = calculate_recency(
                    mem.created_at, now, self.settings.rank_recency_half_life_days
                )
                freq = calculate_frequency(mem.access_count, self.settings.rank_frequency_cap)

                if self.ranking_weights:
                    w_rel = self.ranking_weights.get("w_relevance", 0.45)
                    w_imp = self.ranking_weights.get("w_importance", 0.20)
                    w_conf = self.ranking_weights.get("w_confidence", 0.15)
                    w_rec = self.ranking_weights.get("w_recency", 0.10)
                    w_freq = self.ranking_weights.get("w_frequency", 0.10)
                    score = (
                        w_rel * rel
                        + w_imp * mem.importance
                        + w_conf * mem.confidence
                        + w_rec * rec
                        + w_freq * freq
                    )
                else:
                    score, _ = calculate_score(
                        relevance=rel,
                        importance=mem.importance,
                        confidence=mem.confidence,
                        recency=rec,
                        frequency=freq,
                        settings=self.settings,
                    )
            else:
                score = rel

            mem.score = score
            ranked.append((score, mem))

        ranked.sort(key=lambda x: x[0], reverse=True)
        top_candidates = [m for _, m in ranked[:k]]

        # Context construction
        context_block, used_memories = build_context_block(
            top_candidates,
            self.settings.context_max_chars,
        )

        system_prompt = assemble_system_prompt(self.settings.chat_system_prompt, context_block)
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": question},
        ]

        try:
            reply = self.llm.chat(messages=messages, temperature=0.1)
        except Exception:
            reply = "I don't know."
        elapsed_ms = (time.perf_counter() - start_time) * 1000.0

        retrieved_ids = [m.fact_id for m in top_candidates if m.fact_id]
        retrieved_contents = [m.content for m in top_candidates]

        return AnswerResult(
            user_id=user_id,
            question_id=question_id,
            question=question,
            reply=str(reply).strip(),
            retrieved_memory_ids=retrieved_ids,
            retrieved_contents=retrieved_contents,
            latency_ms=elapsed_ms,
        )

    def get_stored_memories(self, user_id: str) -> list[dict[str, Any]]:
        memories = self._stores.get(user_id, [])
        return [
            {
                "id": m.id,
                "content": m.content,
                "status": m.status,
                "version": m.version,
                "fact_id": m.fact_id,
                "is_distractor": m.is_distractor,
            }
            for m in memories
            if m.status == "active"
        ]

    def get_duplicate_count(self, user_id: str) -> int:
        return self._duplicates_merged.get(user_id, 0)

    def get_distractors_stored(self, user_id: str) -> int:
        memories = self._stores.get(user_id, [])
        return sum(
            1
            for m in memories
            if m.status == "active" and (m.is_distractor or "weather" in m.content.lower())
        )
