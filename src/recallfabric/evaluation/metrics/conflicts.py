"""Conflict-handling accuracy metric."""

from recallfabric.evaluation.metrics.quality import normalize_text


def is_conflict_resolved_correctly(
    prediction: str,
    latest_fact: str | None,
    superseded_fact: str | None,
) -> bool:
    """Check if prediction adopts latest fact and does not retain superseded fact."""
    if not latest_fact:
        return True

    norm_pred = normalize_text(prediction)
    norm_latest = normalize_text(latest_fact)

    # Must contain latest fact
    has_latest = (
        norm_latest == norm_pred
        or f" {norm_latest} " in f" {norm_pred} "
        or norm_pred.startswith(f"{norm_latest} ")
        or norm_pred.endswith(f" {norm_latest}")
    )
    if not has_latest:
        return False

    # Must NOT assert superseded fact
    if superseded_fact:
        norm_superseded = normalize_text(superseded_fact)
        has_superseded = (
            norm_superseded == norm_pred
            or f" {norm_superseded} " in f" {norm_pred} "
            or norm_pred.startswith(f"{norm_superseded} ")
            or norm_pred.endswith(f" {norm_superseded}")
        )
        if has_superseded:
            return False

    return True


def calculate_conflict_accuracy(results: list[bool]) -> float:
    """Calculate overall conflict accuracy (0.0 to 1.0)."""
    if not results:
        return 0.0
    return sum(1 for r in results if r) / float(len(results))
