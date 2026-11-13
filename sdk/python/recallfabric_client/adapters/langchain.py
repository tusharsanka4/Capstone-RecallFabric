"""LangChain retriever and memory adapter for RecallFabric."""

from __future__ import annotations

from typing import Any

from recallfabric_client.client import RecallFabric

try:
    from langchain_core.documents import Document
    from langchain_core.memory import BaseMemory
    from langchain_core.retrievers import BaseRetriever
except ImportError:
    # Graceful fallback when langchain-core is not installed
    class Document:  # type: ignore[no-redef]
        def __init__(self, page_content: str, metadata: dict[str, Any] | None = None) -> None:
            self.page_content = page_content
            self.metadata = metadata or {}

        def __repr__(self) -> str:
            return f"Document(page_content={self.page_content!r}, metadata={self.metadata!r})"

    class BaseRetriever:  # type: ignore[no-redef]
        pass

    class BaseMemory:  # type: ignore[no-redef]
        pass


class RecallFabricRetriever(BaseRetriever):
    """LangChain Retriever backed by RecallFabric."""

    def __init__(
        self,
        client: RecallFabric | None = None,
        user_id: str | None = None,
        limit: int = 5,
        min_similarity: float | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._client = client or RecallFabric()
        self.user_id = user_id
        self.limit = limit
        self.min_similarity = min_similarity

    def _get_relevant_documents(self, query: str, **kwargs: Any) -> list[Document]:
        result = self._client.recall(
            query=query,
            limit=self.limit,
            min_similarity=self.min_similarity,
            user_id=self.user_id,
        )
        docs: list[Document] = []
        for item in result.memories:
            docs.append(
                Document(
                    page_content=item.content,
                    metadata={
                        "id": str(item.id),
                        "type": item.type,
                        "score": item.score,
                        "importance": item.importance,
                        "similarity": item.similarity,
                        **item.metadata,
                    },
                )
            )
        return docs

    def invoke(self, input: str, **kwargs: Any) -> list[Document]:
        return self._get_relevant_documents(input, **kwargs)


class RecallFabricMemory(BaseMemory):
    """LangChain memory adapter that automatically persists and injects conversation context."""

    def __init__(
        self,
        client: RecallFabric | None = None,
        user_id: str | None = None,
        memory_key: str = "context",
        limit: int = 5,
        extract_on_save: bool = True,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._client = client or RecallFabric()
        self.user_id = user_id
        self.memory_key = memory_key
        self.limit = limit
        self.extract_on_save = extract_on_save

    @property
    def memory_variables(self) -> list[str]:
        return [self.memory_key]

    def load_memory_variables(self, inputs: dict[str, Any]) -> dict[str, Any]:
        query = str(inputs.get("input") or inputs.get("human_input") or inputs.get("query") or "")
        if not query:
            return {self.memory_key: ""}

        result = self._client.recall(query=query, limit=self.limit, user_id=self.user_id)
        return {self.memory_key: result.context}

    def save_context(self, inputs: dict[str, Any], outputs: dict[str, Any]) -> None:
        if not self.extract_on_save:
            return

        user_input = str(
            inputs.get("input") or inputs.get("human_input") or inputs.get("query") or ""
        )
        ai_output = str(
            outputs.get("output") or outputs.get("response") or outputs.get("text") or ""
        )
        if user_input:
            text = f"User: {user_input}\nAssistant: {ai_output}"
            try:
                self._client.remember(
                    text=text,
                    extract=True,
                    user_id=self.user_id,
                    source="langchain_memory",
                )
            except Exception:
                pass

    def clear(self) -> None:
        pass
