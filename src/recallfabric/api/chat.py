from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request

from recallfabric.api.extraction import MemoryExtractRequest
from recallfabric.api.extraction import extract_memories as run_extraction
from recallfabric.api.memories import Database, Embedder, retrieve_memories
from recallfabric.context.builder import assemble_system_prompt, build_context_block
from recallfabric.db.models import ApiKey
from recallfabric.providers import (
    LLMProvider,
    OllamaProvider,
    ProviderBadResponse,
    ProviderTimeout,
    ProviderUnavailable,
    get_chat_provider,
)
from recallfabric.schemas.chat import ChatRequest, ChatResponse
from recallfabric.schemas.memory import MemoryRetrieve
from recallfabric.security.auth import get_current_api_key, verify_user_access

router = APIRouter(prefix="/chat", tags=["chat"])


def get_llm_client(request: Request) -> Any:
    existing = getattr(request.app.state, "chat_provider", None)
    if existing is not None:
        return existing
    legacy = getattr(request.app.state, "llm_client", None)
    if legacy is not None:
        return legacy
    settings = request.app.state.settings
    created = get_chat_provider(settings)
    request.app.state.chat_provider = created
    return created


LLMClient = Annotated[Any, Depends(get_llm_client)]
ApiKeyDep = Annotated[ApiKey | None, Depends(get_current_api_key)]


@router.post("", response_model=ChatResponse)
def chat_endpoint(
    payload: ChatRequest,
    session: Database,
    embedder: Embedder,
    client: LLMClient,
    request: Request,
    api_key: ApiKeyDep = None,
):
    settings = request.app.state.settings
    verify_user_access(payload.user_id, api_key, settings)

    retrieval_payload = MemoryRetrieve(
        user_id=payload.user_id,
        query=payload.message,
        limit=settings.chat_retrieval_limit,
        status="active",
        track_access=True,
    )
    retrieval_page = retrieve_memories(
        payload=retrieval_payload,
        session=session,
        embedder=embedder,
        request=request,
        api_key=api_key,
    )

    context_text, used_memories = build_context_block(
        retrieval_page.items,
        settings.context_max_chars,
    )

    system_prompt = assemble_system_prompt(settings.chat_system_prompt, context_text)
    messages = [{"role": "system", "content": system_prompt}]

    if payload.history:
        trimmed_history = payload.history[-settings.chat_history_limit :]
        for item in trimmed_history:
            messages.append({"role": item.role, "content": item.content})

    messages.append({"role": "user", "content": payload.message})

    if isinstance(client, LLMProvider):
        provider = client
    else:
        provider = OllamaProvider(client=client, model=settings.chat_model)

    try:
        reply_text = provider.chat(
            messages=messages,
            temperature=0.4,
            max_tokens=250,
            json_mode=False,
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

    reply = str(reply_text).strip()
    if not reply:
        raise HTTPException(status_code=502, detail="LLM returned invalid response")

    extracted_memories = []
    if payload.extract:
        source = f"chat_{payload.conversation_id}" if payload.conversation_id else "chat"
        extract_req = MemoryExtractRequest(
            user_id=payload.user_id,
            text=payload.message,
            source=source,
        )
        extract_res = run_extraction(
            payload=extract_req,
            session=session,
            embedder=embedder,
            client=client,
            request=request,
            api_key=api_key,
        )
        extracted_memories = extract_res.extracted

    return ChatResponse(
        reply=reply,
        memories_used=used_memories,
        model=provider.model,
        extracted=extracted_memories,
        extracted_memories=extracted_memories,
    )
