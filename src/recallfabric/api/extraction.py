import json
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from recallfabric.api.memories import Database, Embedder
from recallfabric.db.models import ApiKey, Memory
from recallfabric.extraction.filters import filter_candidate
from recallfabric.extraction.prompt import SYSTEM_PROMPT
from recallfabric.memory_manager.conflicts import resolve_conflict_or_store
from recallfabric.memory_manager.dedupe import (
    acquire_dedupe_lock,
    deduplicate_and_store,
    find_duplicate_memory,
)
from recallfabric.memory_manager.events import record_event
from recallfabric.providers import (
    LLMProvider,
    OllamaProvider,
    ProviderBadResponse,
    ProviderTimeout,
    ProviderUnavailable,
    get_extraction_provider,
)
from recallfabric.schemas.memory import MemoryCreate, MemoryRead, NonemptyText
from recallfabric.security.auth import get_current_api_key, verify_user_access
from recallfabric.security.encryption import decrypt_content, encrypt_content

router = APIRouter(prefix="/extraction", tags=["extraction"])

client = None


def get_llm_client(request: Request) -> Any:
    existing = getattr(request.app.state, "extraction_provider", None)
    if existing is not None:
        return existing
    legacy = getattr(request.app.state, "llm_client", None)
    if legacy is not None:
        return legacy
    settings = request.app.state.settings
    created = get_extraction_provider(settings)
    request.app.state.extraction_provider = created
    return created


LLMClient = Annotated[Any, Depends(get_llm_client)]


class MemoryExtractRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: Annotated[NonemptyText, Field(max_length=255)]
    text: NonemptyText
    source: Annotated[NonemptyText, Field(max_length=512)]
    dry_run: bool = False
    deduplicate: bool = True


class RejectedCandidate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    content: str
    reason: str
    type: str | None = None
    importance: float | None = None
    confidence: float | None = None


class ExtractionResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    extracted: list[MemoryRead] = Field(default_factory=list)
    candidates: list[dict[str, Any]] = Field(default_factory=list)
    rejected: list[RejectedCandidate] = Field(default_factory=list)


ApiKeyDep = Annotated[ApiKey | None, Depends(get_current_api_key)]


@router.post("", response_model=ExtractionResponse, status_code=201)
def extract_memories(
    payload: MemoryExtractRequest,
    session: Database,
    embedder: Embedder,
    client: LLMClient,
    request: Request,
    api_key: ApiKeyDep = None,
):
    if not payload.text.strip():
        raise HTTPException(status_code=422, detail="Text cannot be empty")

    settings = request.app.state.settings
    verify_user_access(payload.user_id, api_key, settings)
    enc_key = settings.encryption_key.get_secret_value() if settings.encryption_key else None
    if isinstance(client, LLMProvider):
        provider = client
    else:
        provider = OllamaProvider(client=client, model=settings.extraction_model)

    user_message = f'Extract all atomic facts from this user message:\n"""\n{payload.text}\n"""'
    try:
        result_content = provider.chat(
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            temperature=settings.extraction_temperature,
            json_mode=True,
        )
    except ProviderTimeout as e:
        raise HTTPException(status_code=504, detail="LLM request timed out") from e
    except ProviderUnavailable as e:
        raise HTTPException(status_code=503, detail="LLM service unreachable") from e
    except ProviderBadResponse as e:
        raise HTTPException(status_code=502, detail=f"LLM request failed: {e}") from e
    except Exception as e:
        err_msg = str(e).lower()
        if "timeout" in err_msg:
            raise HTTPException(status_code=504, detail="LLM request timed out") from e
        if "connect" in err_msg or "unreachable" in err_msg:
            raise HTTPException(status_code=503, detail="LLM service unreachable") from e
        raise HTTPException(status_code=502, detail="LLM request failed") from e

    if not result_content:
        raise HTTPException(status_code=502, detail="LLM returned invalid JSON")

    try:
        data = json.loads(result_content)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=502, detail="LLM returned invalid JSON") from e

    if not isinstance(data, dict):
        raise HTTPException(status_code=502, detail="LLM returned invalid JSON")

    if "memories" not in data or not isinstance(data["memories"], list):
        raise HTTPException(status_code=502, detail="LLM returned invalid JSON")

    memories_data = data["memories"]

    valid_candidates = []
    rejected_candidates = []

    for item in memories_data:
        if not isinstance(item, dict):
            continue
        content = str(item.get("content", "")).strip().strip('"').strip("'").strip()
        try:
            importance = float(item.get("importance", 0.0))
            confidence = float(item.get("confidence", 0.0))
        except (ValueError, TypeError):
            rejected_candidates.append(
                RejectedCandidate(
                    content=content,
                    reason="Invalid importance or confidence score",
                )
            )
            continue

        mem_type = str(item.get("type", "fact")).lower().strip()
        if mem_type not in {"preference", "goal", "skill", "profile", "fact", "other"}:
            mem_type = "fact"

        is_valid, reject_reason = filter_candidate(content, importance, confidence, settings)
        if not is_valid:
            rejected_candidates.append(
                RejectedCandidate(
                    content=content,
                    reason=reject_reason or "Quality filter rejected",
                    type=mem_type,
                    importance=importance,
                    confidence=confidence,
                )
            )
            continue

        reason = str(item.get("creation_reason") or "").strip() or "Explicitly stated by user"

        meta = dict(item.get("metadata") or {})
        max_snippet = settings.extraction_max_snippet_chars
        snippet = payload.text[:max_snippet]
        start_char = None
        end_char = None
        idx = payload.text.lower().find(content.lower())
        if idx != -1:
            start_char = idx
            end_char = idx + len(content)
        meta["source_id"] = payload.source
        meta["source_reference"] = {
            "source_id": payload.source,
            "snippet": snippet,
            "start_char": start_char,
            "end_char": end_char,
        }
        meta["snippet"] = snippet
        if start_char is not None:
            meta["character_offsets"] = [start_char, end_char]

        mem_create = MemoryCreate(
            user_id=payload.user_id,
            content=content,
            type=mem_type,
            importance=importance,
            confidence=confidence,
            source=payload.source,
            creation_reason=reason,
            metadata=meta,
        )
        valid_candidates.append(mem_create)

    if payload.dry_run:
        return ExtractionResponse(
            extracted=[],
            candidates=memories_data,
            rejected=rejected_candidates,
        )

    created_memories = []
    if valid_candidates:
        candidates_with_embeddings = [
            (mem_create, embedder.embed(mem_create.content)) for mem_create in valid_candidates
        ]
        with session.begin():
            if payload.deduplicate:
                acquire_dedupe_lock(session, payload.user_id)
            for mem_create, embedding in candidates_with_embeddings:
                if payload.deduplicate:
                    matched, _ = find_duplicate_memory(
                        session=session,
                        user_id=mem_create.user_id,
                        memory_type=mem_create.type,
                        embedding_vector=embedding.vector,
                        embedding_model=embedding.model,
                        embedding_dimensions=embedding.dimensions,
                        threshold=settings.dedupe_threshold,
                    )
                    if matched is not None:
                        memory, action, matched_id = deduplicate_and_store(
                            session=session,
                            user_id=mem_create.user_id,
                            content=mem_create.content,
                            memory_type=mem_create.type,
                            importance=mem_create.importance,
                            confidence=mem_create.confidence,
                            source=mem_create.source,
                            creation_reason=mem_create.creation_reason,
                            metadata=mem_create.metadata,
                            embedding_vector=embedding.vector,
                            embedding_model=embedding.model,
                            embedding_dimensions=embedding.dimensions,
                            threshold=settings.dedupe_threshold,
                        )
                        conflict_info = None
                    else:
                        memory, action, matched_id, conflict_info = resolve_conflict_or_store(
                            session=session,
                            user_id=mem_create.user_id,
                            content=mem_create.content,
                            memory_type=mem_create.type,
                            importance=mem_create.importance,
                            confidence=mem_create.confidence,
                            source=mem_create.source,
                            creation_reason=mem_create.creation_reason,
                            metadata=mem_create.metadata,
                            embedding_vector=embedding.vector,
                            embedding_model=embedding.model,
                            embedding_dimensions=embedding.dimensions,
                            min_similarity=settings.conflict_min_similarity,
                            max_similarity=settings.dedupe_threshold,
                            llm=provider,
                            llm_model=settings.extraction_model,
                            llm_timeout=settings.llm_timeout,
                        )
                    data = MemoryRead.model_validate(memory).model_dump()
                    data["action"] = action
                    data["matched_memory_id"] = matched_id
                    data["conflict_resolution"] = conflict_info
                    if enc_key:
                        data["content"] = decrypt_content(data["content"], enc_key)
                    created_memories.append(MemoryRead.model_validate(data))
                else:
                    values = mem_create.model_dump(exclude={"metadata", "deduplicate"})
                    if enc_key:
                        values["content"] = encrypt_content(mem_create.content, enc_key)
                    memory = Memory(
                        **values,
                        attributes=mem_create.metadata,
                        embedding=embedding.vector,
                        embedding_model=embedding.model,
                        embedding_dimensions=embedding.dimensions,
                    )
                    session.add(memory)
                    session.flush()
                    record_event(
                        session=session,
                        user_id=mem_create.user_id,
                        memory_id=memory.id,
                        memory_version=memory.version,
                        event_type="created",
                        reason=mem_create.creation_reason,
                        source=mem_create.source,
                        actor="user",
                        detail={"confidence": memory.confidence},
                    )
                    mem_dict = MemoryRead.model_validate(memory).model_dump()
                    if enc_key:
                        mem_dict["content"] = decrypt_content(mem_dict["content"], enc_key)
                    created_memories.append(MemoryRead.model_validate(mem_dict))

    return ExtractionResponse(
        extracted=created_memories,
        candidates=memories_data,
        rejected=rejected_candidates,
    )
