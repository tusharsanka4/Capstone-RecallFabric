"""Smoke test running the evaluation pipeline across all 3 systems
with a fake provider and deterministic embedder.
"""

import json
from pathlib import Path

from recallfabric.evaluation.config import EvaluationConfig, MetricsConfig, ProviderConfig
from recallfabric.evaluation.generator import generate_conversations
from recallfabric.evaluation.runner import (
    DeterministicSemanticEmbedder,
    EvaluationRunner,
    MockEvaluationProvider,
)


def test_evaluation_pipeline_smoke_test(tmp_path: Path):
    # 1. Create a 3-conversation dataset
    conversations = generate_conversations(count=3, seed=42)
    assert len(conversations) == 3

    dataset_file = tmp_path / "dataset_smoke.jsonl"
    with open(dataset_file, "w", encoding="utf-8") as f:
        for c in conversations:
            f.write(json.dumps(c.model_dump()) + "\n")

    results_dir = tmp_path / "results"

    config = EvaluationConfig(
        dataset_path=str(dataset_file),
        results_dir=str(results_dir),
        systems=["no_memory", "basic_vector", "recallfabric"],
        k=5,
        provider=ProviderConfig(name="mock", model="mock-test-model"),
        metrics=MetricsConfig(
            exact_match=True,
            fuzzy_match=True,
            llm_judge=True,
            retrieval_k=[1, 3, 5],
            hallucination_check=True,
            conflict_accuracy=True,
            latency_tracking=True,
            memory_efficiency=True,
        ),
    )

    fake_llm = MockEvaluationProvider(name="mock", model="mock-test-model")
    embedder = DeterministicSemanticEmbedder()

    runner = EvaluationRunner(config=config, llm=fake_llm, embedder=embedder)
    report = runner.run(conversations=conversations)

    # Verify report structure
    assert report is not None
    assert "baseline_no_memory" in report.systems
    assert "basic_vector" in report.systems
    assert "recallfabric" in report.systems

    # Verify files created on disk
    timestamp_dir = results_dir / report.timestamp
    assert (timestamp_dir / "results.json").exists()
    assert (timestamp_dir / "summary.csv").exists()

    # Verify System A: No Memory
    sys_a = report.systems["baseline_no_memory"]
    assert sys_a.avg_memories_per_conv == 0.0
    assert sys_a.exact_match == 0.0

    # Verify System B: Basic Vector Memory
    sys_b = report.systems["basic_vector"]
    assert sys_b.avg_memories_per_conv > 0.0
    assert sys_b.distractor_rejection_rate == 0.0  # Stores all messages

    # Verify System C: Full RecallFabric
    sys_c = report.systems["recallfabric"]
    assert sys_c.distractor_rejection_rate == 1.0  # Distractors rejected
    assert sys_c.avg_memories_per_conv < sys_b.avg_memories_per_conv  # Curated facts only
    assert sys_c.conflict_accuracy > sys_b.conflict_accuracy  # Conflict resolution active
