"""Hallucination detection and rate metrics."""

from recallfabric.evaluation.metrics.quality import normalize_text


def is_hallucinated(
    prediction: str,
    contradicted_answers: list[str],
    expected_answer: str,
    is_unanswerable: bool = False,
) -> bool:
    """Detect if prediction asserts a contradicted fact or hallucinates ungrounded info.

    Returns True if:
    1. Prediction mentions any explicitly contradicted fact/phrase (e.g. superseded old fact).
    2. Question is unanswerable / distractor, but prediction claims a definite fact instead
       of acknowledging lack of info.
    """
    norm_pred = normalize_text(prediction)
    if not norm_pred:
        return False

    # Check against known contradicted facts
    for contradicted in contradicted_answers:
        norm_contra = normalize_text(contradicted)
        if norm_contra and (
            f" {norm_contra} " in f" {norm_pred} "
            or norm_pred.startswith(f"{norm_contra} ")
            or norm_pred.endswith(f" {norm_contra}")
            or norm_pred == norm_contra
        ):
            return True

    # If unanswerable question
    if is_unanswerable or normalize_text(expected_answer) in {
        "not specified",
        "i dont know",
        "no information",
        "none",
    }:
        dont_know_phrases = [
            "dont know",
            "do not know",
            "not mentioned",
            "no information",
            "not specified",
            "no record",
            "cant recall",
            "cannot recall",
            "have not mentioned",
            "haven't mentioned",
            "does not state",
        ]
        has_hedging = any(phrase in norm_pred for phrase in dont_know_phrases)
        if not has_hedging:
            # Fabricated an answer for something never stated
            return True

    return False


def calculate_hallucination_rate(hallucination_flags: list[bool]) -> float:
    """Calculate overall hallucination rate (0.0 to 1.0)."""
    if not hallucination_flags:
        return 0.0
    return sum(1 for h in hallucination_flags if h) / float(len(hallucination_flags))
