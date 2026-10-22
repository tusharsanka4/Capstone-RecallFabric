"""Cross-model consistency metrics across providers/models."""

from recallfabric.evaluation.metrics.quality import exact_match_score, fuzzy_match_score


def answers_agree(p1: str, p2: str) -> bool:
    """Check if two model answers agree on the core fact."""
    if exact_match_score(p1, p2) > 0.0 or exact_match_score(p2, p1) > 0.0:
        return True
    if fuzzy_match_score(p1, p2) >= 0.4:
        return True
    return False


def calculate_cross_model_consistency(
    model_predictions: dict[str, list[str]],
) -> dict[str, float]:
    """Compute pairwise and mean agreement across different models on the same questions.

    Returns dict with pairwise agreement rates and overall average agreement.
    """
    models = list(model_predictions.keys())
    if len(models) < 2:
        return {"mean_agreement": 1.0}

    pairwise_agreements = {}
    agreements_list = []

    for i in range(len(models)):
        for j in range(i + 1, len(models)):
            m1, m2 = models[i], models[j]
            preds1 = model_predictions[m1]
            preds2 = model_predictions[m2]
            total = min(len(preds1), len(preds2))
            if total == 0:
                continue

            matches = 0
            for p1, p2 in zip(preds1[:total], preds2[:total], strict=False):
                if answers_agree(p1, p2):
                    matches += 1

            agreement = matches / float(total)
            pairwise_agreements[f"{m1}_vs_{m2}"] = round(agreement, 4)
            agreements_list.append(agreement)

    mean_agreement = sum(agreements_list) / float(len(agreements_list)) if agreements_list else 1.0
    pairwise_agreements["mean_agreement"] = round(mean_agreement, 4)
    return pairwise_agreements
