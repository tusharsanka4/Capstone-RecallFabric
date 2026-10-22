"""Base interface for systems under test in RecallFabric evaluation."""

from abc import ABC, abstractmethod
from typing import Any

from recallfabric.embeddings.service import EmbeddingProvider
from recallfabric.evaluation.models import AnswerResult, IngestResult
from recallfabric.providers.base import LLMProvider


class SystemUnderTest(ABC):
    name: str

    def __init__(self, llm: LLMProvider, embedder: EmbeddingProvider):
        self.llm = llm
        self.embedder = embedder

    @abstractmethod
    def reset(self, user_id: str | None = None) -> None:
        """Reset internal memory state."""
        pass

    @abstractmethod
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
        """Ingest a user message."""
        pass

    @abstractmethod
    def answer(
        self,
        user_id: str,
        question_id: str,
        question: str,
        k: int = 5,
    ) -> AnswerResult:
        """Answer a question for a user."""
        pass

    @abstractmethod
    def get_stored_memories(self, user_id: str) -> list[dict[str, Any]]:
        """Return list of stored memories/messages for a user."""
        pass

    @abstractmethod
    def get_duplicate_count(self, user_id: str) -> int:
        """Return count of redundant/duplicate memories."""
        pass

    @abstractmethod
    def get_distractors_stored(self, user_id: str) -> int:
        """Return count of distractor messages stored."""
        pass
