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
    database_url: SecretStr | None = None
    db_host: str = "127.0.0.1"
    db_port: int = Field(default=5432, ge=1, le=65535)
    db_name: str = "recallfabric"
    db_user: str = "recallfabric"
    db_password: SecretStr = SecretStr("")
    db_connect_timeout: int = Field(default=3, ge=1, le=60)
    db_sslmode: str = Field(default="prefer")
    db_pool_size: int = Field(default=5, ge=1, le=100)
    db_max_overflow: int = Field(default=10, ge=0, le=100)
    db_pool_recycle: int = Field(default=1800, ge=60)
    db_pool_pre_ping: bool = Field(default=True)
    embedding_provider: Literal["fastembed", "openai", "gemini"] = "fastembed"
    embedding_model: str = Field(default="BAAI/bge-small-en-v1.5", min_length=1)
    embedding_cache_dir: Path = Path(".model-cache")
    embedding_threads: int = Field(default=2, ge=1, le=32)
    openai_embedding_model: str = Field(default="text-embedding-3-small")
    openai_embedding_dimensions: int = Field(default=1536, ge=1, le=16000)
    gemini_embedding_model: str = Field(default="text-embedding-004")
    gemini_embedding_dimensions: int = Field(default=768, ge=1, le=16000)
    cors_origins: list[str] | str = Field(default=["*"])
    workers: int = Field(default=1, ge=1, le=64)
    run_migrations: bool = Field(default=False)
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
    allow_public_signup: bool = Field(default=True)
    admin_token: SecretStr = SecretStr("")
    encryption_key: SecretStr = SecretStr("")
    rate_limit_rps: float = Field(default=20.0, ge=0.1, le=10000.0)
    rate_limit_burst: int = Field(default=40, ge=1, le=100000)
    max_request_size_bytes: int = Field(default=1_048_576, ge=1024, le=104_857_600)
    mcp_transport: Literal["stdio", "streamable-http", "sse"] = "stdio"
    mcp_host: str = Field(default="127.0.0.1")
    mcp_port: int = Field(default=8001, ge=1, le=65535)
    mcp_user_id: str | None = None
    proxy_allowed_upstreams: list[str] | str = Field(
        default=[
            "https://api.openai.com",
            "https://api.anthropic.com",
            "https://generativelanguage.googleapis.com",
            "http://127.0.0.1",
            "http://localhost",
            "*",
        ]
    )
    proxy_default_upstream_url: str = Field(default="https://api.openai.com/v1")
    proxy_extract_by_default: bool = Field(default=False)

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

    @model_validator(mode="after")
    def validate_production_settings(self) -> Self:
        if self.environment != "production":
            return self

        # 1. Refuse to start with auth disabled
        if not self.auth_enabled:
            raise ValueError(
                "Production safety error: "
                "Auth cannot be disabled when RECALLFABRIC_ENVIRONMENT=production."
            )

        # 2. Refuse to start with an empty admin token
        if not self.admin_token or not self.admin_token.get_secret_value().strip():
            raise ValueError(
                "Production safety error: "
                "RECALLFABRIC_ADMIN_TOKEN must be set and non-empty in production."
            )

        # 3. Refuse to start with default password
        db_url_str = ""
        if self.database_url:
            db_url_str = self.database_url.get_secret_value()
        db_pass_str = self.db_password.get_secret_value() if self.db_password else ""

        if "recallfabric_local" in db_url_str or db_pass_str == "recallfabric_local":
            raise ValueError(
                "Production safety error: Default database password 'recallfabric_local' "
                "cannot be used in production."
            )

        # 4. LLM Provider selection and API key validation
        if self.llm_provider == "ollama":
            if self.openai_api_key and self.openai_api_key.get_secret_value().strip():
                self.llm_provider = "openai"
            elif self.gemini_api_key and self.gemini_api_key.get_secret_value().strip():
                self.llm_provider = "gemini"
            elif self.anthropic_api_key and self.anthropic_api_key.get_secret_value().strip():
                self.llm_provider = "anthropic"
            else:
                raise ValueError(
                    "Production safety error: Ollama cannot be used in production. "
                    "Configure a hosted LLM provider (openai, anthropic, or gemini) "
                    "and set its API key."
                )

        provider_keys = {
            "openai": (self.openai_api_key, "RECALLFABRIC_OPENAI_API_KEY"),
            "anthropic": (self.anthropic_api_key, "RECALLFABRIC_ANTHROPIC_API_KEY"),
            "gemini": (self.gemini_api_key, "RECALLFABRIC_GEMINI_API_KEY"),
        }
        if self.llm_provider in provider_keys:
            k, var_name = provider_keys[self.llm_provider]
            if not k or not k.get_secret_value().strip():
                raise ValueError(
                    f"Production safety error: Hosted LLM provider '{self.llm_provider}' "
                    f"is configured, but {var_name} is empty."
                )

        if self.chat_provider and self.chat_provider in provider_keys:
            k, var_name = provider_keys[self.chat_provider]
            if not k or not k.get_secret_value().strip():
                raise ValueError(
                    f"Production safety error: Chat provider '{self.chat_provider}' is configured, "
                    f"but {var_name} is empty."
                )
        if self.extraction_provider and self.extraction_provider in provider_keys:
            k, var_name = provider_keys[self.extraction_provider]
            if not k or not k.get_secret_value().strip():
                raise ValueError(
                    f"Production safety error: Extraction provider '{self.extraction_provider}' "
                    f"is configured, but {var_name} is empty."
                )

        # 5. Embedding Provider API key check
        if self.embedding_provider == "openai":
            if not self.openai_api_key or not self.openai_api_key.get_secret_value().strip():
                raise ValueError(
                    "Production safety error: Hosted embedding provider 'openai' requires "
                    "RECALLFABRIC_OPENAI_API_KEY to be set."
                )
        elif self.embedding_provider == "gemini":
            if not self.gemini_api_key or not self.gemini_api_key.get_secret_value().strip():
                raise ValueError(
                    "Production safety error: Hosted embedding provider 'gemini' requires "
                    "RECALLFABRIC_GEMINI_API_KEY to be set."
                )

        return self

    def get_cors_origins(self) -> list[str]:
        if isinstance(self.cors_origins, list):
            return self.cors_origins
        return [origin.strip() for origin in str(self.cors_origins).split(",") if origin.strip()]

    def get_proxy_allowed_upstreams(self) -> list[str]:
        if isinstance(self.proxy_allowed_upstreams, list):
            return self.proxy_allowed_upstreams
        return [
            origin.strip()
            for origin in str(self.proxy_allowed_upstreams).split(",")
            if origin.strip()
        ]

    def is_upstream_allowed(self, url: str) -> bool:
        allowed = self.get_proxy_allowed_upstreams()
        if "*" in allowed:
            return True
        from urllib.parse import urlparse

        parsed = urlparse(url)
        host = parsed.netloc or parsed.path
        host_only = host.split(":")[0] if ":" in host else host

        for pattern in allowed:
            pat_clean = pattern.strip()
            if not pat_clean:
                continue
            if pat_clean == "*":
                return True
            pat_parsed = urlparse(pat_clean)
            pat_host = pat_parsed.netloc or pat_parsed.path
            pat_host_only = pat_host.split(":")[0] if ":" in pat_host else pat_host
            if host_only == pat_host_only or host == pat_host or url.startswith(pat_clean):
                return True
        return False

    def get_database_url(self) -> str:
        """Return resolved and normalized database URL string.

        When database_url is provided, it takes precedence over db_host/port/name/user/password.
        """
        if self.database_url and self.database_url.get_secret_value().strip():
            return normalize_database_url(self.database_url.get_secret_value())

        from sqlalchemy import URL

        return URL.create(
            "postgresql+psycopg",
            username=self.db_user,
            password=self.db_password.get_secret_value() if self.db_password else None,
            host=self.db_host,
            port=self.db_port,
            database=self.db_name,
        ).render_as_string(hide_password=False)


def normalize_database_url(url: str) -> str:
    """Normalize postgres://, postgresql://, or postgresql+psycopg2:// to postgresql+psycopg://."""
    trimmed = url.strip()
    if trimmed.startswith("postgresql+psycopg://"):
        return trimmed
    if trimmed.startswith("postgresql+psycopg2://"):
        return "postgresql+psycopg://" + trimmed[len("postgresql+psycopg2://") :]
    if trimmed.startswith("postgres://"):
        return "postgresql+psycopg://" + trimmed[len("postgres://") :]
    if trimmed.startswith("postgresql://"):
        return "postgresql+psycopg://" + trimmed[len("postgresql://") :]
    return trimmed


def get_settings(request: Request) -> Settings:
    return getattr(request.app.state, "settings", Settings())
