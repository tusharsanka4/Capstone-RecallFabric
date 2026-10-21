import math
from pathlib import Path
from typing import Literal, Self

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from starlette.requests import Request

from recallfabric.context.builder import DEFAULT_CHAT_SYSTEM_PROMPT


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="RECALLFABRIC_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = Field(default="RecallFabric", min_length=1)
    environment: Literal["development", "test", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    db_host: str = "127.0.0.1"
    db_port: int = Field(default=5432, ge=1, le=65535)
    db_name: str = "recallfabric"
    db_user: str = "recallfabric"
    db_password: SecretStr = SecretStr("")
    db_connect_timeout: int = Field(default=3, ge=1, le=60)
    embedding_model: str = Field(default="BAAI/bge-small-en-v1.5", min_length=1)
    embedding_cache_dir: Path = Path(".model-cache")
    embedding_threads: int = Field(default=2, ge=1, le=32)
    llm_base_url: str = Field(default="http://127.0.0.1:11434/v1", min_length=1)
    extraction_model: str = Field(default="qwen2.5:0.5b", min_length=1)
    llm_api_key: SecretStr = SecretStr("ollama")
    llm_timeout: float = Field(default=30.0, ge=1.0, le=600.0)
    extraction_temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    extraction_min_importance: float = Field(default=0.6, ge=0.0, le=1.0)
    extraction_min_confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    retrieval_min_similarity: float = Field(default=0.4, ge=-1.0, le=1.0)
    rank_w_relevance: float = Field(default=0.40, ge=0.0, le=1.0)
    rank_w_importance: float = Field(default=0.20, ge=0.0, le=1.0)
    rank_w_confidence: float = Field(default=0.10, ge=0.0, le=1.0)
    rank_w_recency: float = Field(default=0.15, ge=0.0, le=1.0)
    rank_w_frequency: float = Field(default=0.15, ge=0.0, le=1.0)
    rank_recency_half_life_days: float = Field(default=14.0, gt=0.0)
    rank_frequency_cap: int = Field(default=100, ge=1)
    rank_candidate_multiplier: int = Field(default=3, ge=1, le=20)
    chat_model: str = Field(default="qwen2.5:0.5b", min_length=1)
    context_max_chars: int = Field(default=2000, ge=100)
    chat_system_prompt: str = Field(default=DEFAULT_CHAT_SYSTEM_PROMPT)
    chat_history_limit: int = Field(default=6, ge=0, le=100)
    chat_retrieval_limit: int = Field(default=8, ge=1, le=50)
    dedupe_threshold: float = Field(default=0.92, ge=0.0, le=1.0)
    conflict_min_similarity: float = Field(default=0.70, ge=0.0, le=1.0)
    extraction_max_snippet_chars: int = Field(default=200, ge=10, le=2000)
    llm_provider: Literal["ollama", "openai", "anthropic", "gemini"] = "ollama"
    chat_provider: Literal["ollama", "openai", "anthropic", "gemini"] | None = None
    extraction_provider: Literal["ollama", "openai", "anthropic", "gemini"] | None = None
    openai_api_key: SecretStr = SecretStr("")
    openai_base_url: str = Field(default="https://api.openai.com/v1")
    openai_model: str = Field(default="gpt-4o-mini")
    anthropic_api_key: SecretStr = SecretStr("")
    anthropic_base_url: str = Field(default="https://api.anthropic.com")
    anthropic_model: str = Field(default="claude-3-haiku-20240307")
    gemini_api_key: SecretStr = SecretStr("")
    gemini_base_url: str = Field(default="https://generativelanguage.googleapis.com/v1beta")
    gemini_model: str = Field(default="gemini-1.5-flash")
    auth_enabled: bool | None = None
    admin_token: SecretStr = SecretStr("")
    encryption_key: SecretStr = SecretStr("")
    rate_limit_rps: float = Field(default=20.0, ge=0.1, le=10000.0)
    rate_limit_burst: int = Field(default=40, ge=1, le=100000)
    max_request_size_bytes: int = Field(default=1_048_576, ge=1024, le=104_857_600)
    mcp_transport: Literal["stdio", "streamable-http", "sse"] = "stdio"
    mcp_host: str = Field(default="127.0.0.1")
    mcp_port: int = Field(default=8001, ge=1, le=65535)
    mcp_user_id: str | None = None

    @model_validator(mode="after")
    def resolve_auth_enabled(self) -> Self:
        if self.auth_enabled is None:
            self.auth_enabled = self.environment == "production"
        return self

    @model_validator(mode="after")
    def validate_ranking_weights(self) -> Self:
        total = (
            self.rank_w_relevance
            + self.rank_w_importance
            + self.rank_w_confidence
            + self.rank_w_recency
            + self.rank_w_frequency
        )
        if not math.isclose(total, 1.0, rel_tol=1e-3, abs_tol=1e-3):
            raise ValueError(f"Ranking weights must sum to 1.0, got {total:.4f}")
        return self


def get_settings(request: Request) -> Settings:
    return getattr(request.app.state, "settings", Settings())
