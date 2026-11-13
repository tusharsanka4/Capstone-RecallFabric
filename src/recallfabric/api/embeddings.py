"""Generate query or passage vectors using the configured local model."""

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from recallfabric.embeddings.service import (
    EmbeddingKind,
    EmbeddingProvider,
    EmbeddingResult,
    get_embedding_provider,
)
from recallfabric.schemas.memory import NonemptyText

router = APIRouter(prefix="/embeddings", tags=["embeddings"])


class EmbeddingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: Annotated[NonemptyText, Field(max_length=20000)]
    kind: EmbeddingKind = "query"


@router.post("", response_model=EmbeddingResult, operation_id="generate_embedding")
def generate_embedding(
    payload: EmbeddingRequest,
    provider: Annotated[EmbeddingProvider, Depends(get_embedding_provider)],
):
    return provider.embed(payload.text, kind=payload.kind)
