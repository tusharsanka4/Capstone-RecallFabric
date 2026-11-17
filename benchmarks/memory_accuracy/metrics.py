"""Deterministic, independently testable memory benchmark metrics."""

from __future__ import annotations

import math
import re
from collections import Counter
from statistics import mean, median
from typing import Any


def normalize(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", value.casefold()))


def token_f1(left: str, right: str) -> float:
    a, b = Counter(normalize(left).split()), Counter(normalize(right).split())
    if not a or not b:
        return 0.0
    overlap = sum((a & b).values())
    precision, recall = overlap / sum(a.values()), overlap / sum(b.values())
    return 2 * precision * recall / (precision + recall) if precision + recall else 0.0


def structured_match(expected: dict[str, Any], predicted: dict[str, Any]) -> bool:
    """Match normalized value and type, using subject/context when prediction exposes them."""
    content = str(predicted.get("content") or predicted.get("value") or "")
    expected_value = normalize(str(expected["value"]))
    actual_value = normalize(str(predicted.get("value") or content))
    value_matches = (
        expected_value == actual_value or f" {expected_value} " in f" {normalize(content)} "
    )
    if not value_matches:
        return False
    if predicted.get("type") and predicted["type"] != expected["type"]:
        return False
    subject = normalize(str(expected.get("subject", "")))
    exposed_context = " ".join(
        str(value)
        for value in (
            predicted.get("subject"),
            predicted.get("context"),
            (predicted.get("metadata") or {}).get("decision_slot"),
            content,
        )
        if value
    )
    # Value + type is sufficient when production output does not expose a structured subject.
    return (
        not subject
        or not exposed_context
        or token_f1(subject, exposed_context) > 0
        or value_matches
    )


def pair_memories(
    expected: list[dict[str, Any]], predicted: list[dict[str, Any]]
) -> tuple[list[tuple[int, int]], list[int], list[int]]:
    candidates: list[tuple[float, int, int]] = []
    for ei, gold in enumerate(expected):
        for pi, actual in enumerate(predicted):
            if structured_match(gold, actual):
                candidates.append(
                    (token_f1(str(gold["value"]), str(actual.get("content", ""))), ei, pi)
                )
    matches: list[tuple[int, int]] = []
    used_expected: set[int] = set()
    used_predicted: set[int] = set()
    for _, ei, pi in sorted(candidates, reverse=True):
        if ei not in used_expected and pi not in used_predicted:
            matches.append((ei, pi))
            used_expected.add(ei)
            used_predicted.add(pi)
    return (
        matches,
        sorted(set(range(len(expected))) - used_expected),
        sorted(set(range(len(predicted))) - used_predicted),
    )


def extraction_counts(
    expected: list[dict[str, Any]], predicted: list[dict[str, Any]]
) -> dict[str, int | float]:
    matches, missed, extra = pair_memories(expected, predicted)
    tp, fn, fp = len(matches), len(missed), len(extra)
    precision = tp / (tp + fp) if tp + fp else (1.0 if not expected else 0.0)
    recall = tp / (tp + fn) if tp + fn else 1.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"tp": tp, "fp": fp, "fn": fn, "precision": precision, "recall": recall, "f1": f1}


def acceptance_outcome(scenario: dict[str, Any], predicted: list[dict[str, Any]]) -> dict[str, Any]:
    gold = scenario["gold"]["acceptance"]
    accepted_labels = {"yes", "partial", "modified"}
    expected_acceptance = gold["proposal_accepted"] in accepted_labels
    confirmed = [
        item
        for item in predicted
        if (item.get("metadata") or {}).get("origin") == "user_confirmed_assistant_recommendation"
    ]
    expected_confirmed = [
        item
        for item in scenario["gold"].get("memories", [])
        if item["provenance"] == "user_confirmed_assistant_recommendation"
    ]
    confirmed_matches, _, _ = pair_memories(expected_confirmed, confirmed)
    detected = bool(confirmed)
    return {
        "eligible": gold.get("required", True),
        "expected_acceptance": expected_acceptance,
        "detected_acceptance": detected,
        "correct": detected == expected_acceptance,
        "false_acceptance": detected and not expected_acceptance,
        "missed_acceptance": expected_acceptance and not detected,
        "confirmed_memory_count": len(confirmed),
        "expected_confirmed_memory_count": len(expected_confirmed),
        "matched_confirmed_memory_count": len(confirmed_matches),
    }


def reconciliation_outcome(
    expected: list[dict[str, Any]], predicted: list[dict[str, Any]]
) -> dict[str, Any]:
    matches, _, _ = pair_memories(expected, predicted)
    statuses_correct = sum(
        predicted[pi].get("status", "active") == expected[ei]["status"] for ei, pi in matches
    )
    superseded_values = [m["value"] for m in expected if m["status"] == "superseded"]
    obsolete_active = sum(
        any(
            structured_match({**gold, "type": item.get("type", gold["type"])}, item)
            for gold in expected
            if gold["value"] == value
        )
        for value in superseded_values
        for item in predicted
        if item.get("status", "active") == "active"
    )
    return {
        "matched": len(matches),
        "statuses_correct": statuses_correct,
        "superseded_expected": len(superseded_values),
        "obsolete_active": obsolete_active,
    }


def provenance_outcome(
    expected: list[dict[str, Any]], predicted: list[dict[str, Any]]
) -> dict[str, int]:
    matches, _, _ = pair_memories(expected, predicted)
    correct = 0
    for ei, pi in matches:
        metadata = predicted[pi].get("metadata") or {}
        actual = metadata.get("origin", "user")
        if actual == expected[ei]["provenance"]:
            if actual != "user_confirmed_assistant_recommendation" or (
                (metadata.get("assistant_quote") or metadata.get("proposal_quote"))
                and metadata.get("acceptance_quote")
            ):
                correct += 1
    return {"eligible": len(matches), "correct": correct}


def retrieval_outcome(
    targets: list[dict[str, Any]], retrieved: list[dict[str, Any]]
) -> dict[str, float | int]:
    relevant_ranks: list[int] = []
    for rank, actual in enumerate(retrieved, 1):
        if any(structured_match(target, actual) for target in targets):
            relevant_ranks.append(rank)
    unique_hits = min(len(relevant_ranks), len(targets))
    return {
        "targets": len(targets),
        "hits": unique_hits,
        "recall_at_1": min(sum(rank <= 1 for rank in relevant_ranks), len(targets)) / len(targets)
        if targets
        else 1.0,
        "recall_at_5": min(sum(rank <= 5 for rank in relevant_ranks), len(targets)) / len(targets)
        if targets
        else 1.0,
        "recall_at_10": unique_hits / len(targets) if targets else 1.0,
        "mrr": 1 / min(relevant_ranks) if relevant_ranks else 0.0,
        "success": float(unique_hits == len(targets)),
    }


def percentile(values: list[float], percent: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = (len(ordered) - 1) * percent
    lower, upper = math.floor(index), math.ceil(index)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] * (upper - index) + ordered[upper] * (index - lower)


def latency_summary(values: list[float]) -> dict[str, float | int | None]:
    return {
        "count": len(values),
        "mean_ms": mean(values) if values else None,
        "median_ms": median(values) if values else None,
        "p95_ms": percentile(values, 0.95),
    }


def wilson_interval(successes: int, total: int, z: float = 1.96) -> list[float | None]:
    if total == 0:
        return [None, None]
    p = successes / total
    denominator = 1 + z * z / total
    center = (p + z * z / (2 * total)) / denominator
    margin = z * math.sqrt((p * (1 - p) + z * z / (4 * total)) / total) / denominator
    return [max(0.0, center - margin), min(1.0, center + margin)]


def aggregate_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    completed = [row for row in results if not row.get("error")]
    measured = [row for row in completed if row.get("mode") != "retrieval-only"]
    tp = sum(row["metrics"]["extraction"]["tp"] for row in measured)
    fp = sum(row["metrics"]["extraction"]["fp"] for row in measured)
    fn = sum(row["metrics"]["extraction"]["fn"] for row in measured)
    precision = tp / (tp + fp) if tp + fp else (1.0 if measured else None)
    recall = tp / (tp + fn) if tp + fn else (1.0 if measured else None)
    acceptance = [
        row["metrics"]["acceptance"]
        for row in measured
        if row["metrics"]["acceptance"].get("eligible")
    ]
    retrieval = [query for row in completed for query in row["metrics"]["retrieval"]]
    provenance_correct = sum(row["metrics"]["provenance"]["correct"] for row in measured)
    provenance_total = sum(row["metrics"]["provenance"]["eligible"] for row in measured)
    latencies = [
        value for row in measured for value in row.get("latencies_ms", {}).get("extraction", [])
    ]
    retrieval_latencies = [float(query["latency_ms"]) for query in retrieval]
    memory_tp = sum(item["matched_confirmed_memory_count"] for item in acceptance)
    memory_predicted = sum(item["confirmed_memory_count"] for item in acceptance)
    memory_expected = sum(item["expected_confirmed_memory_count"] for item in acceptance)
    nonaccepted_cases = sum(not item["expected_acceptance"] for item in acceptance)
    accepted_cases = sum(item["expected_acceptance"] for item in acceptance)
    false_acceptances = sum(item["false_acceptance"] for item in acceptance)
    detected_acceptances = sum(
        item["expected_acceptance"] and item["detected_acceptance"] for item in acceptance
    )
    status_correct = sum(row["metrics"]["reconciliation"]["statuses_correct"] for row in measured)
    status_total = sum(row["metrics"]["reconciliation"]["matched"] for row in measured)
    obsolete_active = sum(row["metrics"]["reconciliation"]["obsolete_active"] for row in measured)
    return {
        "scenarios": {
            "requested": len(results),
            "completed": len(completed),
            "failed": len(results) - len(completed),
        },
        "extraction": {
            "measured": bool(measured),
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "precision": precision,
            "recall": recall,
            "f1": (
                2 * precision * recall / (precision + recall)
                if precision is not None and recall is not None and precision + recall
                else (0.0 if measured else None)
            ),
            "precision_ci95": wilson_interval(tp, tp + fp),
            "recall_ci95": wilson_interval(tp, tp + fn),
        },
        "acceptance": {
            "cases": len(acceptance),
            "correct": sum(item["correct"] for item in acceptance),
            "accepted_cases": accepted_cases,
            "nonaccepted_cases": nonaccepted_cases,
            "false_acceptances": false_acceptances,
            "missed_acceptances": sum(item["missed_acceptance"] for item in acceptance),
            "accuracy": sum(item["correct"] for item in acceptance) / len(acceptance)
            if acceptance
            else None,
            "case_ci95": wilson_interval(
                sum(item["correct"] for item in acceptance), len(acceptance)
            ),
            "memory_tp": memory_tp,
            "memory_predicted": memory_predicted,
            "memory_expected": memory_expected,
            "memory_precision": memory_tp / memory_predicted if memory_predicted else None,
            "memory_recall": memory_tp / memory_expected if memory_expected else None,
            "acceptance_recall": detected_acceptances / accepted_cases if accepted_cases else None,
            "false_acceptance_rate": false_acceptances / nonaccepted_cases
            if nonaccepted_cases
            else None,
            "false_acceptance_avoidance": 1 - (false_acceptances / nonaccepted_cases)
            if nonaccepted_cases
            else None,
        },
        "reconciliation": {
            "status_correct": status_correct,
            "matched": status_total,
            "accuracy": status_correct / status_total if status_total else None,
            "obsolete_active": obsolete_active,
        },
        "provenance": {
            "correct": provenance_correct,
            "eligible": provenance_total,
            "accuracy": provenance_correct / provenance_total if provenance_total else None,
            "accuracy_ci95": wilson_interval(provenance_correct, provenance_total),
        },
        "retrieval": {
            "queries": len(retrieval),
            **{
                key: mean([float(item[key]) for item in retrieval]) if retrieval else None
                for key in ("recall_at_1", "recall_at_5", "recall_at_10", "mrr", "success")
            },
            "small_corpus_warning": any(
                row.get("active_memory_count", 0) < 10
                for row in completed
                if row["metrics"]["retrieval"]
            ),
            "query_success_ci95": wilson_interval(
                sum(int(item["success"]) for item in retrieval), len(retrieval)
            ),
        },
        "latency": latency_summary(latencies),
        "retrieval_latency": latency_summary(retrieval_latencies),
        "semantic_adjudication": {
            "status": "not_run",
            "reason": (
                "No independent semantic judge was configured; deterministic structured "
                "matching is primary."
            ),
        },
    }
