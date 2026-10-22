"""LlamaIndex retriever adapter for RecallFabric."""

from __future__ import annotations

from typing import Any

from recallfabric_client.client import RecallFabric

try:
    from llama_index.core.retrievers import BaseRetriever
    from llama_index.core.schema import NodeWithScore, TextNode
except ImportError:
    # Graceful fallback when llama-index-core is not installed
    class TextNode:  # type: ignore[no-redef]
        def __init__(self, text: str, id_: str | None = None, metadata: dict | None = None) -> None:
            self.text = text
            self.id_ = id_
            self.metadata = metadata or {}

    class NodeWithScore:  # type: ignore[no-redef]
        def __init__(self, node: TextNode, score: float = 0.0) -> None:
            self.node = node
            self.score = score

        def __repr__(self) -> str:
            return f"NodeWithScore(node={self.node.text!r}, score={self.score})"

    class BaseRetriever:  # type: ignore[no-redef]
        pass


class RecallFabricLlamaIndexRetriever(BaseRetriever):
    """LlamaIndex Retriever backed by RecallFabric."""

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

    def _retrieve(self, query_bundle: Any) -> list[NodeWithScore]:
        query_str = getattr(query_bundle, "query_str", str(query_bundle))
        result = self._client.recall(
            query=query_str,
            limit=self.limit,
            min_similarity=self.min_similarity,
            user_id=self.user_id,
        )

        nodes: list[NodeWithScore] = []
        for item in result.memories:
            node = TextNode(
                text=item.content,
                id_=str(item.id),
                metadata={
                    "type": item.type,
                    "importance": item.importance,
                    "confidence": item.confidence,
                    "source": item.source,
                    **item.metadata,
                },
            )
            nodes.append(NodeWithScore(node=node, score=item.score))
        return nodes

    def retrieve(self, query_bundle: Any) -> list[NodeWithScore]:
        return self._retrieve(query_bundle)
