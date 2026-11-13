"""Metrics for RecallFabric evaluation framework."""

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

__all__ = [
    "precision_at_k",
    "recall_at_k",
    "normalize_text",
    "exact_match_score",
    "token_f1_score",
    "fuzzy_match_score",
    "llm_judge_score",
    "is_hallucinated",
    "calculate_hallucination_rate",
    "calculate_percentiles",
    "calculate_memory_efficiency",
    "is_conflict_resolved_correctly",
    "calculate_conflict_accuracy",
    "calculate_cross_model_consistency",
]
