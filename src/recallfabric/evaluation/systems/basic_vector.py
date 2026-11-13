"""System B: Basic vector memory (stores every message, top-k cosine similarity only)."""

import math
import time
from typing import Any
from uuid import uuid4

from recallfabric.embeddings.service import EmbeddingProvider
from recallfabric.evaluation.models import AnswerResult, IngestResult
from recallfabric.evaluation.systems.base import SystemUnderTest
from recallfabric.providers.base import LLMProvider


def cosine_similarity(v1: list[float], v2: list[float]) -> float:
    if not v1 or not v2 or len(v1) != len(v2):
        return 0.0
    dot = sum(a * b for a, b in zip(v1, v2, strict=False))
    norm1 = math.sqrt(sum(a * a for a in v1))
    norm2 = math.sqrt(sum(b * b for b in v2))
    if norm1 == 0.0 or norm2 == 0.0:
        return 0.0
    return max(-1.0, min(1.0, dot / (norm1 * norm2)))


class BasicVectorMemorySystem(SystemUnderTest):
    name: str = "basic_vector"

    def __init__(self, llm: LLMProvider, embedder: EmbeddingProvider):
        super().__init__(llm, embedder)
        # user_id -> list of stored message records
        self._stores: dict[str, list[dict[str, Any]]] = {}

    def reset(self, user_id: str | None = None) -> None:
        if user_id:
            self._stores.pop(user_id, None)
        else:
            self._stores.clear()

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

        emb_res = self.embedder.embed(message, kind="passage")
        record = {
            "id": str(uuid4()),
            "message": message,
            "vector": emb_res.vector,
            "fact_id": fact_id,
            "fact_content": fact_content,
            "is_distractor": is_distractor,
            "is_update": is_update,
            "session_id": session_id,
            "created_at": time.time(),
        }
        self._stores[user_id].append(record)
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
        records = self._stores.get(user_id, [])

        if not records:
            # No memories stored
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

        q_emb = self.embedder.embed(question, kind="query")
        scored = []
        for r in records:
            sim = cosine_similarity(q_emb.vector, r["vector"])
            scored.append((sim, r))

        scored.sort(key=lambda x: x[0], reverse=True)
        top_k = scored[:k]

        context_lines = [f"- {r['message']}" for _, r in top_k]
        context_block = "\n".join(context_lines)
        retrieved_ids = [r["fact_id"] for _, r in top_k if r.get("fact_id")]
        retrieved_contents = [r["message"] for _, r in top_k]

        system_prompt = (
            "You are a helpful assistant. Use previous context to answer the question.\n"
            f"Context:\n{context_block}\n\n"
            "If the context does not contain the answer, say you don't know."
        )

        messages = [
            {"role": "system", "content": system_prompt},
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
            retrieved_memory_ids=retrieved_ids,
            retrieved_contents=retrieved_contents,
            latency_ms=elapsed_ms,
        )

    def get_stored_memories(self, user_id: str) -> list[dict[str, Any]]:
        return list(self._stores.get(user_id, []))

    def get_duplicate_count(self, user_id: str) -> int:
        records = self._stores.get(user_id, [])
        if len(records) < 2:
            return 0
        duplicates = 0
        for i in range(len(records)):
            for j in range(i + 1, len(records)):
                sim = cosine_similarity(records[i]["vector"], records[j]["vector"])
                if sim >= 0.85:
                    duplicates += 1
                    break
        return duplicates

    def get_distractors_stored(self, user_id: str) -> int:
        records = self._stores.get(user_id, [])
        return sum(1 for r in records if r.get("is_distractor"))
