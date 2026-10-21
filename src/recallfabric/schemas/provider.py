from pydantic import BaseModel, ConfigDict


class ProviderInfo(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    model: str
    configured: bool
    available: bool
    is_default: bool


class ProvidersResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    providers: list[ProviderInfo]
    default_provider: str
    chat_provider: str
    extraction_provider: str
