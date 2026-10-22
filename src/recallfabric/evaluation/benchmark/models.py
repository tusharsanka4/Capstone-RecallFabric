"""Data models for RecallFabric M18 benchmarking and research results."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ScaleTestResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    scale_size: int
    scale_label: str  # "1k", "10k", "100k"
    flat_latency_ms: float
    hnsw_latency_ms: float
    speedup: float
    hnsw_recall_at_10: float


class MetricStats(BaseModel):
    model_config = ConfigDict(extra="ignore")

    mean: float
    std: float

    def format(self, decimals: int = 4) -> str:
        return f"{self.mean:.{decimals}f} ± {self.std:.{decimals}f}"


class SystemBenchmarkStats(BaseModel):
    model_config = ConfigDict(extra="ignore")

    system_name: str
    precision_at_1: MetricStats
    precision_at_5: MetricStats
    recall_at_1: MetricStats
    recall_at_5: MetricStats
    exact_match: MetricStats
    fuzzy_match: MetricStats
    hallucination_rate: MetricStats
    conflict_accuracy: MetricStats
    answer_latency_p50_ms: MetricStats
    avg_memories_per_conv: MetricStats
    distractor_rejection_rate: MetricStats


class AblationResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    ablation_name: str
    description: str
    precision_at_1: float
    recall_at_1: float
    exact_match: float
    hallucination_rate: float
    conflict_accuracy: float
    avg_memories_per_conv: float
    distractor_rejection_rate: float


class PresetResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    preset_name: str
    description: str
    weights: dict[str, float]
    precision_at_1: float
    recall_at_1: float
    exact_match: float
    fuzzy_match: float
    conflict_accuracy: float


class ProviderBenchmarkResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    provider_name: str
    model: str
    exact_match: float
    fuzzy_match: float
    conflict_accuracy: float
    hallucination_rate: float
    answer_latency_p50_ms: float


class EmbeddingBenchmarkResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    model_name: str
    dimensions: int
    precision_at_1: float
    recall_at_1: float
    ingest_latency_ms: float


class FullBenchmarkReport(BaseModel):
    model_config = ConfigDict(extra="ignore")

    timestamp: str
    seeds: list[int]
    systems_comparison: dict[str, SystemBenchmarkStats] = Field(default_factory=dict)
    ranking_presets: dict[str, PresetResult] = Field(default_factory=dict)
    ablations: dict[str, AblationResult] = Field(default_factory=dict)
    providers: dict[str, ProviderBenchmarkResult] = Field(default_factory=dict)
    embeddings: dict[str, EmbeddingBenchmarkResult] = Field(default_factory=dict)
    scale_tests: list[ScaleTestResult] = Field(default_factory=list)
    raw_runs: list[dict[str, Any]] = Field(default_factory=list)
