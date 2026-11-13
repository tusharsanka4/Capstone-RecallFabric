"""Configuration loading and validation for RecallFabric evaluation."""

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field


class ProviderConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = "mock"  # mock, ollama, openai, anthropic, gemini
    model: str = "mock-model"
    temperature: float = 0.1
    timeout: float = 30.0


class EmbedderConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    type: str = "deterministic"  # deterministic or fastembed
    model: str = "test-retrieval-model"


class MetricsConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    exact_match: bool = True
    fuzzy_match: bool = True
    llm_judge: bool = False
    retrieval_k: list[int] = Field(default_factory=lambda: [1, 3, 5])
    hallucination_check: bool = True
    conflict_accuracy: bool = True
    latency_tracking: bool = True
    memory_efficiency: bool = True


class EvaluationConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    dataset_path: str = "evaluation/data/dataset.jsonl"
    results_dir: str = "evaluation/results"
    systems: list[str] = Field(
        default_factory=lambda: ["no_memory", "basic_vector", "recallfabric"]
    )
    k: int = 5
    provider: ProviderConfig = Field(default_factory=ProviderConfig)
    judge_provider: ProviderConfig | None = None
    embedder: EmbedderConfig = Field(default_factory=EmbedderConfig)
    metrics: MetricsConfig = Field(default_factory=MetricsConfig)
    limit_conversations: int | None = None
    user_id_prefix: str = "eval_"

    @classmethod
    def from_yaml(cls, path: str | Path) -> "EvaluationConfig":
        file_path = Path(path)
        if not file_path.exists():
            raise FileNotFoundError(f"Evaluation config file not found: {path}")
        with open(file_path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return cls.model_validate(data)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump()
