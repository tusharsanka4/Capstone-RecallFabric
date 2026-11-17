"""Artifact writers for the memory accuracy benchmark."""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from .metrics import aggregate_results


def write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8"
    )


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, default=str) + "\n" for row in rows),
        encoding="utf-8",
    )


def format_metric(value: float | None) -> str:
    return f"{value:.3f}" if value is not None else "n/a"


def build_category_rows(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in results:
        grouped[row["category"]].append(row)
    output = []
    for category, rows in sorted(grouped.items()):
        metrics = aggregate_results(rows)
        output.append(
            {
                "category": category,
                "scenarios": len(rows),
                "completed": metrics["scenarios"]["completed"],
                "precision": metrics["extraction"]["precision"],
                "recall": metrics["extraction"]["recall"],
                "f1": metrics["extraction"]["f1"],
                "acceptance_accuracy": metrics["acceptance"]["accuracy"],
                "false_acceptances": metrics["acceptance"]["false_acceptances"],
                "retrieval_recall_at_5": metrics["retrieval"]["recall_at_5"],
            }
        )
    return output


def write_report(
    output_dir: Path, manifest: dict[str, Any], results: list[dict[str, Any]]
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    aggregate = aggregate_results(results)
    category_rows = build_category_rows(results)
    failures = [
        {
            "scenario_id": row["scenario_id"],
            "category": row["category"],
            "error": row.get("error"),
            "fp": row.get("metrics", {}).get("extraction", {}).get("fp"),
            "fn": row.get("metrics", {}).get("extraction", {}).get("fn"),
        }
        for row in results
        if row.get("error")
        or row.get("metrics", {}).get("extraction", {}).get("fp")
        or row.get("metrics", {}).get("extraction", {}).get("fn")
    ]
    write_json(output_dir / "manifest.json", manifest)
    write_jsonl(output_dir / "results.jsonl", results)
    write_json(output_dir / "aggregate_metrics.json", aggregate)
    write_jsonl(output_dir / "failures.jsonl", failures)
    with (output_dir / "category_metrics.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=list(category_rows[0]) if category_rows else ["category"]
        )
        writer.writeheader()
        writer.writerows(category_rows)
    with (output_dir / "failures.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["scenario_id", "category", "error", "fp", "fn"])
        writer.writeheader()
        writer.writerows(failures)

    e, a, r = aggregate["extraction"], aggregate["acceptance"], aggregate["retrieval"]
    caveat = (
        "Yes: at least one evaluated retrieval corpus had fewer than 10 active memories."
        if r["small_corpus_warning"]
        else "No."
    )
    extraction_row = " | ".join(
        [
            str(e["tp"]),
            str(e["fp"]),
            str(e["fn"]),
            format_metric(e["precision"]),
            format_metric(e["recall"]),
            format_metric(e["f1"]),
        ]
    )
    report = f"""# RecallFabric Memory Accuracy Benchmark

## Run scope

- Run ID: `{manifest["run_id"]}`
- Mode: `{manifest["mode"]}`
- Dataset split: `{manifest["split"]}`
- Scenarios: {aggregate["scenarios"]["completed"]} completed,
  {aggregate["scenarios"]["failed"]} failed
- Commit: `{manifest["git"]["commit"]}` ({"dirty" if manifest["git"]["dirty"] else "clean"})

## Extraction accuracy

| TP | FP | FN | Precision | Recall | F1 |
|---:|---:|---:|---:|---:|---:|
| {extraction_row} |

The proposed targets are comparison thresholds, not claims. This run reports observed numerators,
denominators, and Wilson 95% intervals in `aggregate_metrics.json`.

## Recommendation acceptance

- Correct cases: {a["correct"]} / {a["cases"]}
- False acceptances: {a["false_acceptances"]}
- Missed acceptances: {a["missed_acceptances"]}

## Provenance and reconciliation

- Provenance correct: {aggregate["provenance"]["correct"]} / {aggregate["provenance"]["eligible"]}
- Detailed active and superseded outcomes are retained per scenario in `results.jsonl`.

## Retrieval

- Queries: {r["queries"]}
- Recall@1: {r["recall_at_1"] if r["recall_at_1"] is not None else "n/a"}
- Recall@5: {r["recall_at_5"] if r["recall_at_5"] is not None else "n/a"}
- Recall@10: {r["recall_at_10"] if r["recall_at_10"] is not None else "n/a"}
- MRR: {r["mrr"] if r["mrr"] is not None else "n/a"}
- Small corpus caveat: {caveat}

## Performance and reliability

- Extraction latency mean: {aggregate["latency"]["mean_ms"]} ms
- Extraction latency median: {aggregate["latency"]["median_ms"]} ms
- Extraction latency p95: {aggregate["latency"]["p95_ms"]} ms
- Provider and scenario errors are listed in `failures.csv` and `failures.jsonl`.

## Reproducibility

`manifest.json` records the dataset hash, prompt hashes, repository state, Python and OS versions,
provider/model settings, embedding model, database/pgvector versions, timeouts, and selection.
Credentials and secret values are excluded.

## Limitations

- Structured matching is deterministic and value/type aware; token similarity is retained only as
  separate diagnostic evidence and is not an LLM adjudication.
- Replay mode fixes assistant messages and isolates extraction/reconciliation. End-to-end mode uses
  live generated assistant replies, so failures may include chat-generation variation.
- Retrieval scores from corpora under 10 active memories should not be treated as scale evidence.
"""
    (output_dir / "REPORT.md").write_text(report, encoding="utf-8")
    return aggregate
