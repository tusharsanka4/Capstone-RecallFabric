"""FastEmbed adapter. Runtime inference only reads previously downloaded model files."""

import math
from threading import Lock
from typing import Literal, Protocol

from fastapi import Request
from pydantic import BaseModel, ConfigDict, Field, model_validator

from recallfabric.core.config import Settings

EmbeddingKind = Literal["passage", "query"]


class EmbeddingUnavailable(Exception):
    """The configured model could not produce a usable embedding."""


class EmbeddingResult(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)

    model: str = Field(min_length=1, max_length=255)
    dimensions: int = Field(ge=1, le=16000)
    vector: list[float]

    @model_validator(mode="after")
    def validate_vector(self):
        if len(self.vector) != self.dimensions:
            raise ValueError("Embedding dimension mismatch")
        if not any(self.vector) or any(abs(value) > 3.4028235e38 for value in self.vector):
            raise ValueError("Embedding must be a nonzero finite float32 vector")
        return self


class EmbeddingProvider(Protocol):
    model_id: str
    dimensions: int

    def embed(self, text: str, kind: EmbeddingKind = "passage") -> EmbeddingResult: ...


class LocalEmbeddingProvider:
    def __init__(self, settings: Settings):
        from fastembed import TextEmbedding

        models = {item["model"]: item for item in TextEmbedding.list_supported_models()}
        if settings.embedding_model not in models:
            raise ValueError("Unsupported FastEmbed embedding model")
        self.settings = settings
        self.model_id = f"fastembed:{settings.embedding_model}"
        self.dimensions = models[settings.embedding_model]["dim"]
        self._model = None
        self._lock = Lock()

    def _load(self, *, download: bool = False):
        from fastembed import TextEmbedding

        return TextEmbedding(
            model_name=self.settings.embedding_model,
            cache_dir=str(self.settings.embedding_cache_dir.resolve()),
            threads=self.settings.embedding_threads,
            local_files_only=not download,
        )

    def download(self):
        """Explicit setup step; never called by an HTTP request."""
        with self._lock:
            self._model = self._load(download=True)

    def embed(self, text: str, kind: EmbeddingKind = "passage") -> EmbeddingResult:
        if not text.strip():
            raise ValueError("Embedding input must not be blank")
        try:
            # Serializing tokenizer/inference access also prevents duplicate model loads.
            with self._lock:
                if self._model is None:
                    self._model = self._load()
                generator = (
                    self._model.query_embed(text)
                    if kind == "query"
                    else self._model.passage_embed([text])
                )
                vector = [float(value) for value in next(iter(generator))]
            if not all(math.isfinite(value) for value in vector):
                raise ValueError("Non-finite embedding")
            return EmbeddingResult(model=self.model_id, dimensions=self.dimensions, vector=vector)
        except Exception:
            raise EmbeddingUnavailable() from None


def get_embedding_provider(request: Request) -> EmbeddingProvider:
    return request.app.state.embedding_provider
