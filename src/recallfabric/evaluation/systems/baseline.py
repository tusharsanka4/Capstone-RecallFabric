"""System A: Baseline LLM with no memory."""

import time
from typing import Any

from recallfabric.embeddings.service import EmbeddingProvider
from recallfabric.evaluation.models import AnswerResult, IngestResult
from recallfabric.evaluation.systems.base import SystemUnderTest
from recallfabric.providers.base import LLMProvider


class BaselineNoMemory(SystemUnderTest):
    name: str = "baseline_no_memory"

    def __init__(self, llm: LLMProvider, embedder: EmbeddingProvider):
        super().__init__(llm, embedder)

    def reset(self, user_id: str | None = None) -> None:
        pass

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
        # System A retains no memory across sessions
        return IngestResult(
            user_id=user_id,
            message=message,
            memories_stored=0,
            latency_ms=0.0,
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
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a helpful assistant. Answer concisely. "
                    "If you lack prior facts about the user, clearly state that you don't know."
                ),
            },
            {"role": "user", "content": question},
        ]
        try:
            reply = self.llm.chat(messages=messages, temperature=0.1)
        except Exception:
            reply = "I do not have enough information to answer."
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

    def get_stored_memories(self, user_id: str) -> list[dict[str, Any]]:
        return []

    def get_duplicate_count(self, user_id: str) -> int:
        return 0

    def get_distractors_stored(self, user_id: str) -> int:
        return 0
