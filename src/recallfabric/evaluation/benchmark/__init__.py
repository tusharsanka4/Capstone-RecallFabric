"""RecallFabric M18 benchmarking and research evaluation suite."""

from recallfabric.evaluation.benchmark.ablations import run_ablation_benchmarks
from recallfabric.evaluation.benchmark.charts import generate_benchmark_charts
from recallfabric.evaluation.benchmark.models import (
    AblationResult,
    EmbeddingBenchmarkResult,
    FullBenchmarkReport,
    MetricStats,
    PresetResult,
    ProviderBenchmarkResult,
    ScaleTestResult,
    SystemBenchmarkStats,
)
from recallfabric.evaluation.benchmark.presets import run_ranking_preset_benchmarks
from recallfabric.evaluation.benchmark.report import generate_markdown_report
from recallfabric.evaluation.benchmark.runner import BenchmarkRunner, compute_metric_stats
from recallfabric.evaluation.benchmark.scale import ClusteredHNSWIndex, run_scale_benchmark

__all__ = [
    "BenchmarkRunner",
    "compute_metric_stats",
    "run_scale_benchmark",
    "ClusteredHNSWIndex",
    "run_ablation_benchmarks",
    "run_ranking_preset_benchmarks",
    "generate_benchmark_charts",
    "generate_markdown_report",
    "ScaleTestResult",
    "MetricStats",
    "SystemBenchmarkStats",
    "AblationResult",
    "PresetResult",
    "ProviderBenchmarkResult",
    "EmbeddingBenchmarkResult",
    "FullBenchmarkReport",
]
