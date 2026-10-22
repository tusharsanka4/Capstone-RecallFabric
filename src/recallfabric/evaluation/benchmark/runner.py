"""Benchmark runner orchestrating multi-seed, multi-provider,
ablations, scale tests, and report generation.
"""

import json
import math
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from recallfabric.evaluation.benchmark.ablations import run_ablation_benchmarks
from recallfabric.evaluation.benchmark.charts import generate_benchmark_charts
from recallfabric.evaluation.benchmark.models import (
    EmbeddingBenchmarkResult,
    FullBenchmarkReport,
    MetricStats,
    ProviderBenchmarkResult,
    ScaleTestResult,
    SystemBenchmarkStats,
)
from recallfabric.evaluation.benchmark.presets import run_ranking_preset_benchmarks
from recallfabric.evaluation.benchmark.report import generate_markdown_report
from recallfabric.evaluation.benchmark.scale import run_scale_benchmark
from recallfabric.evaluation.config import EvaluationConfig, MetricsConfig, ProviderConfig
from recallfabric.evaluation.generator import generate_conversations, generate_dataset_file
from recallfabric.evaluation.runner import (
    DeterministicSemanticEmbedder,
    EvaluationRunner,
    MockEvaluationProvider,
    create_embedder,
    create_llm_provider,
)


def compute_metric_stats(values: list[float]) -> MetricStats:
    if not values:
        return MetricStats(mean=0.0, std=0.0)
    mean = sum(values) / float(len(values))
    if len(values) > 1:
        variance = sum((x - mean) ** 2 for x in values) / float(len(values) - 1)
        std = math.sqrt(variance)
    else:
        std = 0.0
    return MetricStats(mean=round(mean, 4), std=round(std, 4))


class BenchmarkRunner:
    def __init__(
        self,
        seeds: list[int] | None = None,
        dataset_path: str = "evaluation/data/dataset.jsonl",
        output_dir: str = "evaluation/results",
        limit_conversations: int | None = None,
        run_scale: bool = True,
        scale_sizes: list[int] | None = None,
        provider_name: str = "mock",
        embedder_type: str = "deterministic",
    ):
        self.seeds = seeds or [42, 43, 44]
        self.dataset_path = dataset_path
        self.output_dir = output_dir
        self.limit_conversations = limit_conversations
        self.run_scale = run_scale
        self.scale_sizes = scale_sizes or [1000, 10000, 100000]
        self.provider_name = provider_name
        self.embedder_type = embedder_type

    def run(self) -> FullBenchmarkReport:
        timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        out_dir = Path(self.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        dataset_file = Path(self.dataset_path)
        if not dataset_file.exists():
            generate_dataset_file(output_path=dataset_file, count=50, seed=42)

        # 1. Multi-Seed System Comparison
        all_seed_runs: list[dict[str, Any]] = []
        systems = ["baseline_no_memory", "basic_vector", "recallfabric"]
        metric_collectors: dict[str, dict[str, list[float]]] = {
            s: {
                "p1": [],
                "p5": [],
                "r1": [],
                "r5": [],
                "em": [],
                "fm": [],
                "halluc": [],
                "conflict": [],
                "ans_p50": [],
                "mem": [],
                "rejection": [],
            }
            for s in systems
        }

        # Initialize base embedder and provider
        cfg = EvaluationConfig(
            dataset_path=self.dataset_path,
            results_dir=self.output_dir,
            limit_conversations=self.limit_conversations,
            provider=ProviderConfig(name=self.provider_name),
            metrics=MetricsConfig(llm_judge=False),
        )
        base_embedder = create_embedder(cfg)
        base_llm = create_llm_provider(cfg)

        for s_val in self.seeds:
            # Deterministically sample / generate conversations for this seed
            convs = generate_conversations(count=self.limit_conversations or 50, seed=s_val)
            runner = EvaluationRunner(config=cfg, llm=base_llm, embedder=base_embedder)
            run_rep = runner.run(conversations=convs)
            all_seed_runs.append(run_rep.model_dump())

            for sys_name in systems:
                if sys_name in run_rep.systems:
                    sm = run_rep.systems[sys_name]
                    mc = metric_collectors[sys_name]
                    mc["p1"].append(sm.precision_at_k.get("1", 0.0))
                    mc["p5"].append(sm.precision_at_k.get("5", 0.0))
                    mc["r1"].append(sm.recall_at_k.get("1", 0.0))
                    mc["r5"].append(sm.recall_at_k.get("5", 0.0))
                    mc["em"].append(sm.exact_match)
                    mc["fm"].append(sm.fuzzy_match)
                    mc["halluc"].append(sm.hallucination_rate)
                    mc["conflict"].append(sm.conflict_accuracy)
                    mc["ans_p50"].append(sm.answer_p50_ms)
                    mc["mem"].append(sm.avg_memories_per_conv)
                    mc["rejection"].append(sm.distractor_rejection_rate)

        systems_comparison: dict[str, SystemBenchmarkStats] = {}
        for sys_name in systems:
            mc = metric_collectors[sys_name]
            systems_comparison[sys_name] = SystemBenchmarkStats(
                system_name=sys_name,
                precision_at_1=compute_metric_stats(mc["p1"]),
                precision_at_5=compute_metric_stats(mc["p5"]),
                recall_at_1=compute_metric_stats(mc["r1"]),
                recall_at_5=compute_metric_stats(mc["r5"]),
                exact_match=compute_metric_stats(mc["em"]),
                fuzzy_match=compute_metric_stats(mc["fm"]),
                hallucination_rate=compute_metric_stats(mc["halluc"]),
                conflict_accuracy=compute_metric_stats(mc["conflict"]),
                answer_latency_p50_ms=compute_metric_stats(mc["ans_p50"]),
                avg_memories_per_conv=compute_metric_stats(mc["mem"]),
                distractor_rejection_rate=compute_metric_stats(mc["rejection"]),
            )

        # 2. Ranking Weight Presets Benchmark
        convs_sample = generate_conversations(count=self.limit_conversations or 50, seed=42)
        presets_results = run_ranking_preset_benchmarks(
            convs_sample, llm=base_llm, embedder=base_embedder
        )

        # 3. Component Ablation Study
        ablation_results = run_ablation_benchmarks(
            convs_sample, llm=base_llm, embedder=base_embedder
        )

        # 4. Multi-Provider Comparison
        provider_results: dict[str, ProviderBenchmarkResult] = {}
        # Test mock and any configured provider
        providers_to_test = [
            ("Mock Provider", MockEvaluationProvider(name="mock", model="mock-eval-v1"))
        ]
        try:
            from recallfabric.providers import get_provider

            ollama_p = get_provider("ollama", model="llama3.2")
            if ollama_p.is_available():
                providers_to_test.append(("Ollama (llama3.2)", ollama_p))
        except Exception:
            pass

        for p_label, p_inst in providers_to_test:
            p_runner = EvaluationRunner(config=cfg, llm=p_inst, embedder=base_embedder)
            target_convs = convs_sample[:5] if self.limit_conversations is None else convs_sample
            p_rep = p_runner.run(conversations=target_convs)
            if "recallfabric" in p_rep.systems:
                rf_m = p_rep.systems["recallfabric"]
                provider_results[p_label] = ProviderBenchmarkResult(
                    provider_name=p_label,
                    model=p_inst.model,
                    exact_match=rf_m.exact_match,
                    fuzzy_match=rf_m.fuzzy_match,
                    conflict_accuracy=rf_m.conflict_accuracy,
                    hallucination_rate=rf_m.hallucination_rate,
                    answer_latency_p50_ms=rf_m.answer_p50_ms,
                )

        # 5. Embedding Models Benchmark
        embedding_results: dict[str, EmbeddingBenchmarkResult] = {}
        embedding_models_to_test = [
            ("deterministic-semantic-v1", DeterministicSemanticEmbedder(dimensions=128)),
            ("deterministic-semantic-compact", DeterministicSemanticEmbedder(dimensions=64)),
        ]
        for emb_label, emb_inst in embedding_models_to_test:
            e_runner = EvaluationRunner(config=cfg, llm=base_llm, embedder=emb_inst)
            e_rep = e_runner.run(conversations=convs_sample[:5])
            if "recallfabric" in e_rep.systems:
                rf_m = e_rep.systems["recallfabric"]
                embedding_results[emb_label] = EmbeddingBenchmarkResult(
                    model_name=emb_label,
                    dimensions=emb_inst.dimensions,
                    precision_at_1=rf_m.precision_at_k.get("1", 0.0),
                    recall_at_1=rf_m.recall_at_k.get("1", 0.0),
                    ingest_latency_ms=rf_m.ingest_p50_ms,
                )

        # 6. Scale Test (1k, 10k, 100k)
        scale_results: list[ScaleTestResult] = []
        if self.run_scale:
            scale_results = run_scale_benchmark(sizes=self.scale_sizes, seed=42)

        # 7. Build Full Benchmark Report
        report = FullBenchmarkReport(
            timestamp=timestamp,
            seeds=self.seeds,
            systems_comparison=systems_comparison,
            ranking_presets=presets_results,
            ablations=ablation_results,
            providers=provider_results,
            embeddings=embedding_results,
            scale_tests=scale_results,
            raw_runs=all_seed_runs,
        )

        # 8. Save raw JSON results
        raw_json_path = out_dir / "benchmark_raw.json"
        with open(raw_json_path, "w", encoding="utf-8") as f:
            json.dump(report.model_dump(), f, indent=2, ensure_ascii=False)

        # 9. Generate Charts & Markdown Report
        generate_benchmark_charts(report, out_dir)
        generate_markdown_report(report, out_dir)

        return report
