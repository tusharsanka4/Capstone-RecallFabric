"""Validated settings loaded from environment variables and a local .env file."""

from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


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
