"""Answer quality metrics: exact match and fuzzy match."""

import re
import string
from collections import Counter


def normalize_text(text: str) -> str:
    """Lowercase, remove punctuation, remove articles, and normalize whitespace."""
    if not text:
        return ""
    text = text.lower()
    # Remove punctuation
    text = "".join(ch for ch in text if ch not in string.punctuation)
    # Remove articles
    text = re.sub(r"\b(a|an|the)\b", " ", text)
    # Normalize whitespace
    text = " ".join(text.split())
    return text.strip()


def exact_match_score(
    prediction: str,
    ground_truth: str,
    acceptable: list[str] | None = None,
) -> float:
    """Exact match metric.

    Returns 1.0 if normalized prediction matches normalized ground_truth
    or any normalized acceptable answer, or if normalized answer is contained
    as a complete phrase in normalized prediction.
    """
    norm_pred = normalize_text(prediction)
    candidates = [ground_truth] + (acceptable or [])
    norm_candidates = [normalize_text(c) for c in candidates if c]

    for norm_c in norm_candidates:
        if norm_pred == norm_c:
            return 1.0
        # If the candidate phrase appears as a distinct phrase in prediction
        if norm_c and (
            f" {norm_c} " in f" {norm_pred} "
            or norm_pred.startswith(f"{norm_c} ")
            or norm_pred.endswith(f" {norm_c}")
        ):
            return 1.0

    return 0.0


def token_f1_score(prediction: str, ground_truth: str) -> float:
    """Token-level F1 score between prediction and ground truth."""
    pred_tokens = normalize_text(prediction).split()
    gt_tokens = normalize_text(ground_truth).split()

    if not pred_tokens or not gt_tokens:
        return 1.0 if pred_tokens == gt_tokens else 0.0

    common = Counter(pred_tokens) & Counter(gt_tokens)
    num_same = sum(common.values())

    if num_same == 0:
        return 0.0

    precision = 1.0 * num_same / len(pred_tokens)
    recall = 1.0 * num_same / len(gt_tokens)
    f1 = (2.0 * precision * recall) / (precision + recall)
    return f1


def fuzzy_match_score(
    prediction: str,
    ground_truth: str,
    acceptable: list[str] | None = None,
) -> float:
    """Fuzzy match score: max token F1 score across all acceptable answers."""
    candidates = [ground_truth] + (acceptable or [])
    scores = [token_f1_score(prediction, c) for c in candidates if c]
    return max(scores) if scores else 0.0
