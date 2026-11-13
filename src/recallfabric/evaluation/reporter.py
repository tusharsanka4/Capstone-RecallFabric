"""Result reporting: JSON and CSV export."""

import csv
import json
from pathlib import Path

from recallfabric.evaluation.models import EvaluationReport, SystemMetrics


def save_evaluation_results(
    report: EvaluationReport, results_base_dir: str | Path
) -> tuple[Path, Path]:
    """Save full JSON results and CSV summary to evaluation/results/<timestamp>/."""
    base_dir = Path(results_base_dir)
    timestamp_dir = base_dir / report.timestamp
    timestamp_dir.mkdir(parents=True, exist_ok=True)

    json_path = timestamp_dir / "results.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report.model_dump(), f, indent=2, ensure_ascii=False)

    csv_path = timestamp_dir / "summary.csv"
    csv_headers = [
        "system",
        "precision@1",
        "precision@3",
        "precision@5",
        "recall@1",
        "recall@3",
        "recall@5",
        "exact_match",
        "fuzzy_match",
        "llm_judge",
        "hallucination_rate",
        "conflict_accuracy",
        "ingest_p50_ms",
        "ingest_p95_ms",
        "answer_p50_ms",
        "answer_p95_ms",
        "avg_memories_per_conv",
        "duplicate_rate",
        "distractor_rejection_rate",
    ]

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=csv_headers)
        writer.writeheader()
        for sys_name, m in report.systems.items():
            row = {
                "system": sys_name,
                "precision@1": m.precision_at_k.get("1", 0.0),
                "precision@3": m.precision_at_k.get("3", 0.0),
                "precision@5": m.precision_at_k.get("5", 0.0),
                "recall@1": m.recall_at_k.get("1", 0.0),
                "recall@3": m.recall_at_k.get("3", 0.0),
                "recall@5": m.recall_at_k.get("5", 0.0),
                "exact_match": round(m.exact_match, 4),
                "fuzzy_match": round(m.fuzzy_match, 4),
                "llm_judge": round(m.llm_judge, 4) if m.llm_judge is not None else "N/A",
                "hallucination_rate": round(m.hallucination_rate, 4),
                "conflict_accuracy": round(m.conflict_accuracy, 4),
                "ingest_p50_ms": m.ingest_p50_ms,
                "ingest_p95_ms": m.ingest_p95_ms,
                "answer_p50_ms": m.answer_p50_ms,
                "answer_p95_ms": m.answer_p95_ms,
                "avg_memories_per_conv": m.avg_memories_per_conv,
                "duplicate_rate": m.duplicate_rate,
                "distractor_rejection_rate": m.distractor_rejection_rate,
            }
            writer.writerow(row)

    return json_path, csv_path


def format_console_table(systems: dict[str, SystemMetrics]) -> str:
    """Format ASCII table comparing systems on all metrics."""
    headers = [
        "System",
        "P@1",
        "P@5",
        "R@1",
        "R@5",
        "Exact",
        "Fuzzy",
        "Halluc",
        "Conflict",
        "Ans_p50",
        "Mem/Conv",
        "Rejection",
    ]
    rows = []
    for sys_name, m in systems.items():
        rows.append(
            [
                sys_name,
                f"{m.precision_at_k.get('1', 0.0):.2f}",
                f"{m.precision_at_k.get('5', 0.0):.2f}",
                f"{m.recall_at_k.get('1', 0.0):.2f}",
                f"{m.recall_at_k.get('5', 0.0):.2f}",
                f"{m.exact_match:.2f}",
                f"{m.fuzzy_match:.2f}",
                f"{m.hallucination_rate:.2f}",
                f"{m.conflict_accuracy:.2f}",
                f"{m.answer_p50_ms:.1f}ms",
                f"{m.avg_memories_per_conv:.1f}",
                f"{m.distractor_rejection_rate:.2f}",
            ]
        )

    col_widths = [len(h) for h in headers]
    for row in rows:
        for idx, cell in enumerate(row):
            col_widths[idx] = max(col_widths[idx], len(cell))

    def make_row(cells):
        return " | ".join(cell.ljust(col_widths[i]) for i, cell in enumerate(cells))

    separator = "-+-".join("-" * w for w in col_widths)
    header_str = make_row(headers)
    table_lines = [header_str, separator]
    for r in rows:
        table_lines.append(make_row(r))

    return "\n".join(table_lines)
