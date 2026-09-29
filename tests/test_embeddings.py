from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from recallfabric.core.config import Settings
from recallfabric.embeddings.service import (
    EmbeddingResult,
    EmbeddingUnavailable,
    LocalEmbeddingProvider,
    get_embedding_provider,
)
from recallfabric.main import create_app


@pytest.mark.parametrize(
    "vector, dimensions",
    [
        ([1, 2], 3),
        ([0, 0], 2),
        ([float("nan")], 1),
        ([float("inf")], 1),
        ([1e40], 1),
    ],
)
def test_invalid_vectors_rejected(vector, dimensions):
    with pytest.raises(ValidationError):
        EmbeddingResult(model="test", dimensions=dimensions, vector=vector)


def test_adapter_uses_distinct_query_and_passage_methods():
    provider = LocalEmbeddingProvider(Settings(_env_file=None))
    provider.dimensions = 3
    provider._model = Mock()
    provider._model.query_embed.return_value = iter([[1, 2, 3]])
    provider._model.passage_embed.return_value = iter([[3, 2, 1]])
    assert provider.embed("question", kind="query").vector == [1, 2, 3]
    assert provider.embed("memory").vector == [3, 2, 1]
    provider._model.query_embed.assert_called_once_with("question")
    provider._model.passage_embed.assert_called_once_with(["memory"])


def test_load_failure_is_sanitized(monkeypatch):
    provider = LocalEmbeddingProvider(Settings(_env_file=None))
    monkeypatch.setattr(provider, "_load", Mock(side_effect=RuntimeError("private path")))
    with pytest.raises(EmbeddingUnavailable) as error:
        provider.embed("test")
    assert "private" not in str(error.value)


def test_runtime_loader_is_offline(monkeypatch):
    provider = LocalEmbeddingProvider(Settings(_env_file=None))
    loader = Mock()
    monkeypatch.setattr("fastembed.TextEmbedding", loader)
    provider._load()
    assert loader.call_args.kwargs["local_files_only"] is True


def test_embedding_endpoint_and_input_validation():
    app = create_app(Settings(_env_file=None))
    provider = Mock()
    provider.embed.return_value = EmbeddingResult(model="test", dimensions=3, vector=[1, 2, 3])
    app.dependency_overrides[get_embedding_provider] = lambda: provider
    with TestClient(app) as client:
        response = client.post("/embeddings", json={"text": "question"})
        assert response.status_code == 200
        assert response.json()["dimensions"] == 3
        provider.embed.assert_called_once_with("question", kind="query")
        assert client.post("/embeddings", json={"text": " "}).status_code == 422
        assert client.post("/embeddings", json={"text": "ok", "kind": "bad"}).status_code == 422
        provider.embed.side_effect = EmbeddingUnavailable()
        assert client.post("/embeddings", json={"text": "ok"}).status_code == 503
