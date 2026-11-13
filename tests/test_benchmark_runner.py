"""Unit tests for M18 benchmark runner on tiny fixtures with fake provider."""

from pathlib import Path

from recallfabric.evaluation.benchmark.runner import BenchmarkRunner, compute_metric_stats
from recallfabric.evaluation.benchmark.scale import run_scale_benchmark


def test_compute_metric_stats():
    values = [0.80, 0.85, 0.90]
    stats = compute_metric_stats(values)
    assert stats.mean == 0.85
    assert stats.std > 0.0
    assert "0.8500 ±" in stats.format(4)

    # Empty list
    empty_stats = compute_metric_stats([])
    assert empty_stats.mean == 0.0
    assert empty_stats.std == 0.0


def test_scale_benchmark_tiny():
    # Test scale runner with small synthetic counts
    results = run_scale_benchmark(sizes=[50, 200], seed=42, dim=32, top_k=5)
    assert len(results) == 2
    assert results[0].scale_size == 50
    assert results[1].scale_size == 200
    assert results[0].hnsw_recall_at_10 >= 0.60
    assert results[1].flat_latency_ms >= 0.0
    assert results[1].hnsw_latency_ms >= 0.0


def test_benchmark_runner_tiny_fixture(tmp_path: Path):
    output_dir = tmp_path / "bench_results"

    runner = BenchmarkRunner(
        seeds=[42, 43],
        output_dir=str(output_dir),
        limit_conversations=2,
        run_scale=True,
        scale_sizes=[50, 100],
        provider_name="mock",
    )
    report = runner.run()

    assert report is not None
    assert len(report.seeds) == 2
    assert "baseline_no_memory" in report.systems_comparison
    assert "basic_vector" in report.systems_comparison
    assert "recallfabric" in report.systems_comparison

    # Presets
    assert "default" in report.ranking_presets
    assert "relevance-only" in report.ranking_presets
    assert "recency-heavy" in report.ranking_presets

    # Ablations
    assert "full" in report.ablations
    assert "no_ranking" in report.ablations
    assert "no_dedupe" in report.ablations
    assert "no_conflicts" in report.ablations
    assert "no_extraction_filters" in report.ablations

    # Files created on disk
    raw_json = output_dir / "benchmark_raw.json"
    report_md = output_dir / "REPORT.md"
    assert raw_json.exists()
    assert report_md.exists()
