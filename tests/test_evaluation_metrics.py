"""Unit tests for RecallFabric evaluation metrics."""

import pytest

from recallfabric.evaluation.metrics.conflicts import (
    calculate_conflict_accuracy,
    is_conflict_resolved_correctly,
)
from recallfabric.evaluation.metrics.consistency import calculate_cross_model_consistency
from recallfabric.evaluation.metrics.efficiency import calculate_memory_efficiency
from recallfabric.evaluation.metrics.hallucination import (
    calculate_hallucination_rate,
    is_hallucinated,
)
from recallfabric.evaluation.metrics.judge import llm_judge_score
from recallfabric.evaluation.metrics.latency import calculate_percentiles
from recallfabric.evaluation.metrics.quality import (
    exact_match_score,
    fuzzy_match_score,
    normalize_text,
    token_f1_score,
)
from recallfabric.evaluation.metrics.retrieval import precision_at_k, recall_at_k
from recallfabric.providers.base import LLMProvider


class MockJudgeProvider(LLMProvider):
    name = "mock_judge"
    model = "mock-judge-v1"

    def __init__(self, score: int = 5, reason: str = "Good"):
        self.score = score
        self.reason = reason

    def is_available(self) -> bool:
        return True

    def chat(self, messages, temperature=0.0, max_tokens=None, json_mode=False) -> str:
        return f'{{"score": {self.score}, "reason": "{self.reason}"}}'


def test_retrieval_precision_and_recall_at_k():
    retrieved = ["mem_1", "mem_2", "mem_3", "mem_4", "mem_5"]
    expected = ["mem_2", "mem_3", "mem_9"]

    # At k=1: retrieved has ["mem_1"], relevant in top-1: 0
    assert precision_at_k(retrieved, expected, k=1) == 0.0
    assert recall_at_k(retrieved, expected, k=1) == 0.0

    # At k=3: retrieved has ["mem_1", "mem_2", "mem_3"], relevant: 2
    assert precision_at_k(retrieved, expected, k=3) == pytest.approx(2 / 3.0)
    assert recall_at_k(retrieved, expected, k=3) == pytest.approx(2 / 3.0)

    # At k=5: retrieved has 5, relevant: 2
    assert precision_at_k(retrieved, expected, k=5) == pytest.approx(2 / 5.0)
    assert recall_at_k(retrieved, expected, k=5) == pytest.approx(2 / 3.0)

    # Empty expected: negative test
    assert precision_at_k([], [], k=5) == 1.0
    assert recall_at_k([], [], k=5) == 1.0
    assert precision_at_k(["mem_1"], [], k=5) == 0.0

    # Edge cases: k <= 0
    assert precision_at_k(retrieved, expected, k=0) == 0.0
    assert recall_at_k(retrieved, expected, k=0) == 0.0


def test_answer_quality_normalization():
    assert normalize_text("  The User Lives In Berlin!  ") == "user lives in berlin"
    assert normalize_text("A cat, a dog, and an owl.") == "cat dog and owl"


def test_answer_quality_exact_match():
    # Direct exact match
    assert exact_match_score("Tokyo", "Tokyo") == 1.0
    # Casing and punctuation
    assert exact_match_score("tokyo!", "Tokyo") == 1.0
    # Phrase in sentence
    assert exact_match_score("You currently live in Tokyo.", "Tokyo") == 1.0
    # Acceptable answers list
    assert exact_match_score("In Tokyo", "Tokyo", acceptable=["In Tokyo", "Tokyo, Japan"]) == 1.0
    # Complete mismatch
    assert exact_match_score("London", "Tokyo") == 0.0


def test_answer_quality_fuzzy_match():
    # Identical
    assert fuzzy_match_score("Rust programming language", "Rust programming language") == 1.0
    # Partial token overlap
    f1 = token_f1_score("Rust is my main language", "My main language is Rust")
    assert f1 > 0.8
    # Zero overlap
    assert token_f1_score("Python", "Rust") == 0.0


def test_llm_as_judge():
    mock_5 = MockJudgeProvider(score=5, reason="Perfect")
    score_5, reason_5 = llm_judge_score(mock_5, "Where do I live?", "Tokyo", "Tokyo")
    assert score_5 == 1.0
    assert "Perfect" in reason_5

    mock_1 = MockJudgeProvider(score=1, reason="Completely wrong")
    score_1, reason_1 = llm_judge_score(mock_1, "Where do I live?", "Tokyo", "London")
    assert score_1 == 0.0
    assert "Completely wrong" in reason_1

    mock_3 = MockJudgeProvider(score=3, reason="Partial")
    score_3, _ = llm_judge_score(mock_3, "Where do I live?", "Tokyo", "In Japan somewhere")
    assert score_3 == 0.5


def test_hallucination_detection_and_rate():
    # Citing contradicted superseded fact
    assert is_hallucinated(
        prediction="You live in Berlin.",
        contradicted_answers=["Berlin"],
        expected_answer="Tokyo",
    )

    # Correct latest fact is not hallucinated
    assert not is_hallucinated(
        prediction="You live in Tokyo.",
        contradicted_answers=["Berlin"],
        expected_answer="Tokyo",
    )

    # Unanswerable question asserting a fact is hallucination
    assert is_hallucinated(
        prediction="You drive a Ferrari 488.",
        contradicted_answers=["Ferrari"],
        expected_answer="Not specified",
        is_unanswerable=True,
    )

    # Unanswerable question admitting ignorance is not hallucinated
    assert not is_hallucinated(
        prediction="I don't know what car you drive.",
        contradicted_answers=["Ferrari"],
        expected_answer="Not specified",
        is_unanswerable=True,
    )

    # Rate calculation
    flags = [True, False, False, True]
    assert calculate_hallucination_rate(flags) == 0.5
    assert calculate_hallucination_rate([]) == 0.0


def test_latency_percentiles():
    latencies = [10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0, 90.0, 100.0]
    p50, p95 = calculate_percentiles(latencies)
    assert p50 == pytest.approx(55.0, abs=1.0)
    assert p95 == pytest.approx(95.5, abs=2.0)

    # Empty list
    assert calculate_percentiles([]) == (0.0, 0.0)
    # Single item
    assert calculate_percentiles([42.0]) == (42.0, 42.0)


def test_memory_efficiency_metric():
    memories_per_conv = [3, 4, 3]  # total 10, avg 3.33
    dupes = [1, 0, 1]  # 2 dupes / 10 memories = 0.2
    distractors_stored = [0, 0, 0]  # 0 stored
    total_distractors = [2, 2, 2]  # 6 total -> rejection 1.0

    eff = calculate_memory_efficiency(
        memories_per_conv=memories_per_conv,
        duplicate_counts=dupes,
        distractors_stored=distractors_stored,
        total_distractors=total_distractors,
    )
    assert eff["avg_memories_per_conv"] == 3.33
    assert eff["duplicate_rate"] == 0.2
    assert eff["distractor_rejection_rate"] == 1.0

    # Basic vector storing all distractors
    eff_b = calculate_memory_efficiency(
        memories_per_conv=[8, 8],
        duplicate_counts=[2, 2],
        distractors_stored=[4, 4],
        total_distractors=[4, 4],
    )
    assert eff_b["distractor_rejection_rate"] == 0.0


def test_conflict_handling_accuracy():
    # Correct: has latest, lacks superseded
    assert is_conflict_resolved_correctly(
        prediction="You moved and now live in Tokyo.",
        latest_fact="Tokyo",
        superseded_fact="Berlin",
    )

    # Incorrect: still claims old fact
    assert not is_conflict_resolved_correctly(
        prediction="You live in Berlin.",
        latest_fact="Tokyo",
        superseded_fact="Berlin",
    )

    # Incorrect: claims both or contradictory
    assert not is_conflict_resolved_correctly(
        prediction="You live in Tokyo and Berlin.",
        latest_fact="Tokyo",
        superseded_fact="Berlin",
    )

    # Accuracy calculation
    res = [True, True, False, True]
    assert calculate_conflict_accuracy(res) == 0.75
    assert calculate_conflict_accuracy([]) == 0.0


def test_cross_model_consistency():
    preds_m1 = ["Tokyo", "Rust", "Golden retriever"]
    preds_m2 = ["You live in Tokyo", "Rust", "Golden retriever"]
    preds_m3 = ["London", "Python", "Cat"]

    consistency_high = calculate_cross_model_consistency(
        {
            "m1": preds_m1,
            "m2": preds_m2,
        }
    )
    assert consistency_high["mean_agreement"] == 1.0

    consistency_low = calculate_cross_model_consistency(
        {
            "m1": preds_m1,
            "m3": preds_m3,
        }
    )
    assert consistency_low["mean_agreement"] == 0.0
