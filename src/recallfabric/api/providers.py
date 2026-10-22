from fastapi import APIRouter, Request

from recallfabric.providers import get_provider
from recallfabric.schemas.provider import ProviderInfo, ProvidersResponse

router = APIRouter(prefix="/providers", tags=["providers"])


@router.get("", response_model=ProvidersResponse, operation_id="get_providers")
def list_providers(request: Request):
    settings = request.app.state.settings
    names = ["ollama", "openai", "anthropic", "gemini"]
    items: list[ProviderInfo] = []

    for name in names:
        prov = get_provider(provider_type=name, settings=settings)
        configured = True
        if name == "openai":
            configured = bool(settings.openai_api_key.get_secret_value())
        elif name == "anthropic":
            configured = bool(settings.anthropic_api_key.get_secret_value())
        elif name == "gemini":
            configured = bool(settings.gemini_api_key.get_secret_value())

        is_avail = prov.is_available() if configured else False
        items.append(
            ProviderInfo(
                name=name,
                model=prov.model,
                configured=configured,
                available=is_avail,
                is_default=(settings.llm_provider == name),
            )
        )

    return ProvidersResponse(
        providers=items,
        default_provider=settings.llm_provider,
        chat_provider=settings.chat_provider or settings.llm_provider,
        extraction_provider=settings.extraction_provider or settings.llm_provider,
    )
