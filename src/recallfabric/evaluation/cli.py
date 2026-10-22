"""Command-line interface for RecallFabric evaluation and benchmarking framework."""

import argparse
import json
import sys
from pathlib import Path

from recallfabric.evaluation.benchmark.charts import generate_benchmark_charts
from recallfabric.evaluation.benchmark.models import FullBenchmarkReport
from recallfabric.evaluation.benchmark.report import generate_markdown_report
from recallfabric.evaluation.benchmark.runner import BenchmarkRunner
from recallfabric.evaluation.config import EvaluationConfig
from recallfabric.evaluation.generator import generate_dataset_file
from recallfabric.evaluation.reporter import format_console_table
from recallfabric.evaluation.runner import EvaluationRunner


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m recallfabric.evaluation",
        description="RecallFabric Evaluation & Benchmarking Framework CLI",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # run subcommand (M17)
    run_parser = subparsers.add_parser(
        "run", help="Run evaluation benchmarks across systems A vs B vs C"
    )
    run_parser.add_argument(
        "--config",
        type=str,
        default="evaluation/config.yaml",
        help="Path to evaluation YAML configuration file",
    )
    run_parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of conversations to evaluate",
    )
    run_parser.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help="Override results output directory",
    )

    # benchmark subcommand (M18)
    bench_parser = subparsers.add_parser(
        "benchmark", help="Run comprehensive research benchmarks and generate REPORT.md"
    )
    bench_parser.add_argument(
        "--seeds",
        type=str,
        default="42,43,44",
        help="Comma-separated repeated random seeds (e.g. 42,43,44)",
    )
    bench_parser.add_argument(
        "--dataset",
        type=str,
        default="evaluation/data/dataset.jsonl",
        help="Path to evaluation dataset JSONL file",
    )
    bench_parser.add_argument(
        "--output-dir",
        type=str,
        default="evaluation/results",
        help="Directory to store benchmark_raw.json, REPORT.md, and charts/",
    )
    bench_parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit conversations for quick verification",
    )
    bench_parser.add_argument(
        "--skip-scale",
        action="store_true",
        help="Skip vector scale test benchmark",
    )
    bench_parser.add_argument(
        "--scale-sizes",
        type=str,
        default="1000,10000,100000",
        help="Comma-separated vector scale sizes for HNSW benchmark",
    )
    bench_parser.add_argument(
        "--provider",
        type=str,
        default="mock",
        help="LLM provider name (mock, ollama, openai, anthropic, gemini)",
    )
    bench_parser.add_argument(
        "--report-only",
        action="store_true",
        help="Regenerate REPORT.md and charts from existing raw benchmark results",
    )
    bench_parser.add_argument(
        "--raw-results",
        type=str,
        default="evaluation/results/benchmark_raw.json",
        help="Path to raw benchmark results JSON for report regeneration",
    )

    # report subcommand (Acceptance criterion: one command regenerates REPORT.md and charts)
    report_parser = subparsers.add_parser(
        "report", help="Regenerate REPORT.md and charts from raw results JSON"
    )
    report_parser.add_argument(
        "--results",
        type=str,
        default="evaluation/results/benchmark_raw.json",
        help="Path to raw benchmark results JSON",
    )
    report_parser.add_argument(
        "--output-dir",
        type=str,
        default="evaluation/results",
        help="Output directory for REPORT.md and charts/",
    )

    # generate subcommand
    gen_parser = subparsers.add_parser("generate", help="Generate synthetic multi-session dataset")
    gen_parser.add_argument(
        "--count",
        type=int,
        default=50,
        help="Number of conversations to generate",
    )
    gen_parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Deterministic random seed",
    )
    gen_parser.add_argument(
        "--seeds",
        type=str,
        default="evaluation/data/seeds.json",
        help="Path to hand-written seed templates file",
    )
    gen_parser.add_argument(
        "--output",
        type=str,
        default="evaluation/data/dataset.jsonl",
        help="Output dataset JSONL file path",
    )

    return parser


def handle_report_regeneration(results_path: str | Path, output_dir: str | Path) -> int:
    res_file = Path(results_path)
    if not res_file.exists():
        print(f"Error: Raw benchmark results not found at {res_file}", file=sys.stderr)
        return 1

    with open(res_file, encoding="utf-8") as f:
        data = json.load(f)
    report = FullBenchmarkReport.model_validate(data)

    print(f"Regenerating charts and REPORT.md from {res_file}...")
    charts = generate_benchmark_charts(report, output_dir)
    report_path = generate_markdown_report(report, output_dir)

    print("Successfully regenerated:")
    print(f"  - Report: {report_path}")
    for k, p in charts.items():
        print(f"  - Chart ({k}): {p}")
    return 0


def main(args: list[str] | None = None) -> int:
    parser = build_parser()
    parsed = parser.parse_args(args)

    if parsed.command == "generate":
        print(f"Generating {parsed.count} deterministic conversations (seed={parsed.seed})...")
        out_path = generate_dataset_file(
            output_path=parsed.output,
            count=parsed.count,
            seed=parsed.seed,
            seed_path=parsed.seeds,
        )
        print(f"Dataset successfully created at: {out_path}")
        return 0

    if parsed.command == "report":
        return handle_report_regeneration(parsed.results, parsed.output_dir)

    if parsed.command == "run":
        config_path = Path(parsed.config)
        if not config_path.exists():
            print(f"Error: Config file not found at {config_path}", file=sys.stderr)
            return 1

        config = EvaluationConfig.from_yaml(config_path)
        if parsed.limit is not None:
            config.limit_conversations = parsed.limit
        if parsed.output_dir is not None:
            config.results_dir = parsed.output_dir

        dataset_path = Path(config.dataset_path)
        if not dataset_path.exists():
            print(f"Dataset not found at {dataset_path}. Auto-generating 50 conversations...")
            generate_dataset_file(output_path=dataset_path, count=50, seed=42)

        print("=" * 80)
        print("RecallFabric Evaluation Benchmark (M17)")
        print(f"Config: {config_path}")
        print(f"Dataset: {config.dataset_path}")
        print(f"Systems under test: {', '.join(config.systems)}")
        print("=" * 80)

        runner = EvaluationRunner(config=config)
        report = runner.run()

        print("\nBenchmark Results Summary:")
        print(format_console_table(report.systems))
        print(f"\nArtifacts generated in: {Path(config.results_dir) / report.timestamp}")
        print("  - results.json (complete evaluation records)")
        print("  - summary.csv (tabular comparison across A vs B vs C)")
        return 0

    if parsed.command == "benchmark":
        if parsed.report_only:
            return handle_report_regeneration(parsed.raw_results, parsed.output_dir)

        seeds = [int(s.strip()) for s in parsed.seeds.split(",") if s.strip()]
        scale_sizes = [int(s.strip()) for s in parsed.scale_sizes.split(",") if s.strip()]

        print("=" * 80)
        print("RecallFabric Research Benchmark Suite (M18)")
        print(f"Seeds: {seeds}")
        print(f"Dataset: {parsed.dataset}")
        print(f"Scale Test Sizes: {scale_sizes if not parsed.skip_scale else 'Skipped'}")
        print(f"Output Directory: {parsed.output_dir}")
        print("=" * 80)

        runner = BenchmarkRunner(
            seeds=seeds,
            dataset_path=parsed.dataset,
            output_dir=parsed.output_dir,
            limit_conversations=parsed.limit,
            run_scale=not parsed.skip_scale,
            scale_sizes=scale_sizes,
            provider_name=parsed.provider,
        )
        report = runner.run()

        print("\nBenchmark Run Complete!")
        print(f"  - Raw Results JSON: {Path(parsed.output_dir) / 'benchmark_raw.json'}")
        print(f"  - Research Report: {Path(parsed.output_dir) / 'REPORT.md'}")
        print(f"  - Charts Directory: {Path(parsed.output_dir) / 'charts'}")
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
