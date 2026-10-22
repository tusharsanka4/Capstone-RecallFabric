"""Matplotlib chart generation for RecallFabric benchmark results."""

from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")  # Non-interactive headless backend
import matplotlib.pyplot as plt

from recallfabric.evaluation.benchmark.models import (
    AblationResult,
    FullBenchmarkReport,
    PresetResult,
    ScaleTestResult,
)


def generate_benchmark_charts(
    report: FullBenchmarkReport, output_dir: str | Path
) -> dict[str, Path]:
    """Generate PNG charts from benchmark results and save to charts/ directory."""
    charts_dir = Path(output_dir) / "charts"
    charts_dir.mkdir(parents=True, exist_ok=True)

    generated = {}

    # 1. System Comparison Chart
    comp_path = charts_dir / "system_comparison.png"
    _plot_system_comparison(report.systems_comparison, comp_path)
    generated["system_comparison"] = comp_path

    # 2. Ablations Chart
    ablation_path = charts_dir / "ablations.png"
    _plot_ablations(report.ablations, ablation_path)
    generated["ablations"] = ablation_path

    # 3. Ranking Presets Chart
    preset_path = charts_dir / "ranking_presets.png"
    _plot_ranking_presets(report.ranking_presets, preset_path)
    generated["ranking_presets"] = preset_path

    # 4. Scale Test Latency & Recall Chart
    scale_path = charts_dir / "scale_latency.png"
    _plot_scale_latency(report.scale_tests, scale_path)
    generated["scale_latency"] = scale_path

    return generated


def _plot_system_comparison(systems_stats: dict[str, Any], output_file: Path) -> None:
    plt.figure(figsize=(10, 5.5), dpi=200)

    systems = list(systems_stats.keys())
    metrics = ["P@1", "R@1", "Exact Match", "Conflict Acc", "Hallucination"]

    # Colors: baseline (gray/neutral), basic vector (amber/coral), recallfabric (indigo/teal)
    colors = ["#94a3b8", "#f97316", "#0ea5e9", "#6366f1"]
    x = range(len(metrics))
    bar_width = 0.22

    for idx, sys_name in enumerate(systems):
        stats = systems_stats[sys_name]
        vals = [
            stats.precision_at_1.mean,
            stats.recall_at_1.mean,
            stats.exact_match.mean,
            stats.conflict_accuracy.mean,
            stats.hallucination_rate.mean,
        ]
        pos = [i + idx * bar_width for i in x]
        display_name = sys_name.replace("_", " ").title()
        plt.bar(
            pos,
            vals,
            width=bar_width,
            label=display_name,
            color=colors[idx % len(colors)],
            alpha=0.9,
        )

    plt.xlabel("Evaluation Metric", fontweight="bold")
    plt.ylabel("Score (0.0 to 1.0)", fontweight="bold")
    plt.title("System Under Test Comparison (Mean across Seeds)", fontweight="bold", fontsize=13)
    plt.xticks([i + bar_width * (len(systems) - 1) / 2.0 for i in x], metrics)
    plt.ylim(0.0, 1.05)
    plt.grid(axis="y", linestyle="--", alpha=0.4)
    plt.legend(frameon=True, loc="upper right")
    plt.tight_layout()
    plt.savefig(output_file)
    plt.close()


def _plot_ablations(ablations: dict[str, AblationResult], output_file: Path) -> None:
    plt.figure(figsize=(9, 5), dpi=200)

    configs = list(ablations.keys())
    labels = [c.replace("_", " ").title() for c in configs]
    p1_scores = [ablations[c].precision_at_1 for c in configs]
    conflict_scores = [ablations[c].conflict_accuracy for c in configs]
    rejection_scores = [ablations[c].distractor_rejection_rate for c in configs]

    x = range(len(configs))
    width = 0.25

    plt.bar([i - width for i in x], p1_scores, width=width, label="Precision@1", color="#3b82f6")
    plt.bar(x, conflict_scores, width=width, label="Conflict Accuracy", color="#10b981")
    plt.bar(
        [i + width for i in x],
        rejection_scores,
        width=width,
        label="Distractor Rejection",
        color="#8b5cf6",
    )

    plt.xlabel("Ablation Configuration", fontweight="bold")
    plt.ylabel("Score (0.0 to 1.0)", fontweight="bold")
    plt.title("RecallFabric Component Ablation Study", fontweight="bold", fontsize=13)
    plt.xticks(x, labels, rotation=15)
    plt.ylim(0.0, 1.1)
    plt.grid(axis="y", linestyle="--", alpha=0.4)
    plt.legend(frameon=True, loc="lower left")
    plt.tight_layout()
    plt.savefig(output_file)
    plt.close()


def _plot_ranking_presets(presets: dict[str, PresetResult], output_file: Path) -> None:
    plt.figure(figsize=(8, 4.5), dpi=200)

    names = list(presets.keys())
    labels = [n.replace("_", " ").title() for n in names]
    p1 = [presets[n].precision_at_1 for n in names]
    r1 = [presets[n].recall_at_1 for n in names]
    em = [presets[n].exact_match for n in names]

    x = range(len(names))
    width = 0.22

    plt.bar([i - width for i in x], p1, width=width, label="Precision@1", color="#6366f1")
    plt.bar(x, r1, width=width, label="Recall@1", color="#06b6d4")
    plt.bar([i + width for i in x], em, width=width, label="Exact Match", color="#ec4899")

    plt.xlabel("Ranking Preset", fontweight="bold")
    plt.ylabel("Score", fontweight="bold")
    plt.title("Ranking Weight Presets Comparison", fontweight="bold", fontsize=13)
    plt.xticks(x, labels)
    plt.ylim(0.0, 1.05)
    plt.grid(axis="y", linestyle="--", alpha=0.4)
    plt.legend(frameon=True, loc="lower right")
    plt.tight_layout()
    plt.savefig(output_file)
    plt.close()


def _plot_scale_latency(scale_results: list[ScaleTestResult], output_file: Path) -> None:
    plt.figure(figsize=(9, 5), dpi=200)

    labels = [r.scale_label for r in scale_results]
    flat_lat = [r.flat_latency_ms for r in scale_results]
    hnsw_lat = [r.hnsw_latency_ms for r in scale_results]
    recall = [r.hnsw_recall_at_10 for r in scale_results]

    fig, ax1 = plt.subplots(figsize=(8.5, 4.8), dpi=200)

    color_flat = "#ef4444"
    color_hnsw = "#10b981"
    ax1.set_xlabel("Vector Count (Scale)", fontweight="bold")
    ax1.set_ylabel("Query Latency (ms, log scale)", color="#1e293b", fontweight="bold")
    ax1.plot(
        labels, flat_lat, marker="o", linewidth=2.5, color=color_flat, label="Flat Scan (No Index)"
    )
    ax1.plot(
        labels, hnsw_lat, marker="s", linewidth=2.5, color=color_hnsw, label="HNSW Index Search"
    )
    ax1.set_yscale("log")
    ax1.grid(True, linestyle="--", alpha=0.4)

    ax2 = ax1.twinx()
    color_rec = "#6366f1"
    ax2.set_ylabel("HNSW Recall@10", color=color_rec, fontweight="bold")
    ax2.plot(
        labels,
        recall,
        marker="^",
        linewidth=2,
        linestyle=":",
        color=color_rec,
        label="HNSW Recall@10",
    )
    ax2.set_ylim(0.80, 1.02)

    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, loc="center left", frameon=True)

    plt.title(
        "Vector Scale Test: Retrieval Latency & Recall (1k, 10k, 100k)",
        fontweight="bold",
        fontsize=12,
    )
    plt.tight_layout()
    plt.savefig(output_file)
    plt.close()
