"""Retrieval metrics: Precision@k and Recall@k."""


def precision_at_k(retrieved_ids: list[str], expected_ids: list[str], k: int) -> float:
    """Calculate precision at k.

    Precision@k = (number of relevant items in top-k) / k.
    If expected_ids is empty:
      - If no items retrieved in top-k: precision = 1.0 (correctly retrieved nothing)
      - If items were retrieved: precision = 0.0 (retrieved irrelevant items)
    """
    if k <= 0:
        return 0.0

    top_k = retrieved_ids[:k]
    if not expected_ids:
        return 1.0 if len(top_k) == 0 else 0.0

    if not top_k:
        return 0.0

    expected_set = set(expected_ids)
    relevant_retrieved = sum(1 for item in top_k if item in expected_set)
    return relevant_retrieved / float(k)


def recall_at_k(retrieved_ids: list[str], expected_ids: list[str], k: int) -> float:
    """Calculate recall at k.

    Recall@k = (number of relevant items in top-k) / (total number of relevant items).
    If expected_ids is empty: recall = 1.0 (all 0 relevant items were recalled).
    """
    if not expected_ids:
        return 1.0

    if k <= 0 or not retrieved_ids:
        return 0.0

    top_k = retrieved_ids[:k]
    expected_set = set(expected_ids)
    relevant_retrieved = sum(1 for item in top_k if item in expected_set)
    return relevant_retrieved / float(len(expected_set))
