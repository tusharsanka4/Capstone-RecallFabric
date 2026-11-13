"""Unit tests verifying report generation and chart creation for M18."""

import json
from pathlib import Path

from recallfabric.evaluation.benchmark.charts import generate_benchmark_charts
from recallfabric.evaluation.benchmark.models import (
    AblationResult,
    FullBenchmarkReport,
    MetricStats,
    PresetResult,
    ScaleTestResult,
    SystemBenchmarkStats,
)
from recallfabric.evaluation.benchmark.report import generate_markdown_report
from recallfabric.evaluation.cli import handle_report_regeneration


def _build_dummy_report() -> FullBenchmarkReport:
    stats_mock = SystemBenchmarkStats(
        system_name="recallfabric",
        precision_at_1=MetricStats(mean=0.85, std=0.02),
        precision_at_5=MetricStats(mean=0.30, std=0.01),
        recall_at_1=MetricStats(mean=0.95, std=0.01),
        recall_at_5=MetricStats(mean=0.98, std=0.01),
        exact_match=MetricStats(mean=0.82, std=0.03),
        fuzzy_match=MetricStats(mean=0.88, std=0.02),
        hallucination_rate=MetricStats(mean=0.05, std=0.01),
        conflict_accuracy=MetricStats(mean=0.95, std=0.02),
        answer_latency_p50_ms=MetricStats(mean=1.2, std=0.1),
        avg_memories_per_conv=MetricStats(mean=2.8, std=0.2),
        distractor_rejection_rate=MetricStats(mean=1.0, std=0.0),
    )

    ablations = {
        "full": AblationResult(
            ablation_name="full",
            description="Full",
            precision_at_1=0.85,
            recall_at_1=0.95,
            exact_match=0.82,
            hallucination_rate=0.05,
            conflict_accuracy=0.95,
            avg_memories_per_conv=2.8,
            distractor_rejection_rate=1.0,
        ),
        "no_conflicts": AblationResult(
            ablation_name="no_conflicts",
            description="No Conflicts",
            precision_at_1=0.60,
            recall_at_1=0.70,
            exact_match=0.45,
            hallucination_rate=0.40,
            conflict_accuracy=0.20,
            avg_memories_per_conv=4.5,
            distractor_rejection_rate=1.0,
        ),
    }

    presets = {
        "default": PresetResult(
            preset_name="default",
            description="Default weights",
            weights={
                "w_relevance": 0.45,
                "w_importance": 0.20,
                "w_confidence": 0.15,
                "w_recency": 0.10,
                "w_frequency": 0.10,
            },
            precision_at_1=0.85,
            recall_at_1=0.95,
            exact_match=0.82,
            fuzzy_match=0.88,
            conflict_accuracy=0.95,
        )
    }

    scale = [
        ScaleTestResult(
            scale_size=1000,
            scale_label="1k",
            flat_latency_ms=1.5,
            hnsw_latency_ms=0.3,
            speedup=5.0,
            hnsw_recall_at_10=0.98,
        )
    ]

    return FullBenchmarkReport(
        timestamp="20261022_120000",
        seeds=[42, 43],
        systems_comparison={"recallfabric": stats_mock},
        ranking_presets=presets,
        ablations=ablations,
        scale_tests=scale,
    )


def test_report_and_chart_generation(tmp_path: Path):
    report = _build_dummy_report()
    charts = generate_benchmark_charts(report, tmp_path)

    assert "system_comparison" in charts
    assert "ablations" in charts
    assert "ranking_presets" in charts
    assert "scale_latency" in charts

    for chart_path in charts.values():
        assert chart_path.exists()
        assert chart_path.stat().st_size > 1000  # Non-empty image file

    report_path = generate_markdown_report(report, tmp_path)
    assert report_path.exists()
    content = report_path.read_text(encoding="utf-8")
    assert "# RecallFabric Benchmark & Research Evaluation Report" in content
    assert "System Comparison" in content
    assert "Component Ablation Study" in content
    assert "Scale Test" in content
    assert "Reproduction Command List" in content


def test_handle_report_regeneration(tmp_path: Path):
    report = _build_dummy_report()
    raw_json = tmp_path / "benchmark_raw.json"
    with open(raw_json, "w", encoding="utf-8") as f:
        json.dump(report.model_dump(), f)

    out_dir = tmp_path / "regenerated"
    ret = handle_report_regeneration(raw_json, out_dir)
    assert ret == 0
    assert (out_dir / "REPORT.md").exists()
    assert (out_dir / "charts" / "system_comparison.png").exists()
