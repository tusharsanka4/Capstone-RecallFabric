"""Run the extraction-quality corpus against a live RecallFabric API."""

from __future__ import annotations

import argparse
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from urllib.request import Request, urlopen


def normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", " ", text.lower()).replace("  ", " ").strip()


def call_api(base_url: str, case: dict) -> dict:
    payload = {
        "user_id": "extraction-quality-eval",
        "source": "extraction-quality-eval",
        "text": case["text"],
        "dry_run": True,
        "deduplicate": True,
    }
    request = Request(
        f"{base_url.rstrip('/')}/extraction",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=180) as response:
        return {
            "status_code": response.status,
            "body": json.load(response),
        }


def evaluate_case(case: dict, result: dict) -> dict:
    body = result["body"]
    candidates = body.get("candidates", [])
    rejected_contents = {
        normalize(str(item.get("content", ""))) for item in body.get("rejected", [])
    }
    normalized_candidates = [normalize(str(item.get("content", ""))) for item in candidates]
    keywords = [normalize(item) for item in case["expected_keywords"]]
    matched = bool(keywords) and all(
        any(keyword in candidate for candidate in normalized_candidates) for keyword in keywords
    )
    accepted_candidates = [
        candidate for candidate in normalized_candidates if candidate not in rejected_contents
    ]
    accepted = bool(accepted_candidates)
    accepted_matched = bool(keywords) and all(
        any(keyword in candidate for candidate in accepted_candidates) for keyword in keywords
    )
    if case["should_extract"]:
        true_positive = matched
        false_negative = not matched
        accepted_false_negative = not accepted_matched
        false_positive = False
    else:
        true_positive = False
        false_negative = False
        accepted_false_negative = False
        false_positive = accepted
    return {
        "case": case,
        "http_status": result["status_code"],
        "candidates": candidates,
        "rejected": body.get("rejected", []),
        "matched_ground_truth": matched,
        "accepted_candidate": accepted,
        "model_generated_candidate": bool(candidates),
        "accepted_false_negative": accepted_false_negative,
        "true_positive": true_positive,
        "false_positive": false_positive,
        "false_negative": false_negative,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8001")
    parser.add_argument(
        "--dataset",
        default="evaluation/data/extraction_quality.jsonl",
    )
    parser.add_argument("--output", default="evaluation/results/extraction_quality_raw.json")
    args = parser.parse_args()

    cases = [
        json.loads(line)
        for line in Path(args.dataset).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    results = []
    for case in cases:
        try:
            results.append(evaluate_case(case, call_api(args.base_url, case)))
        except Exception as exc:
            results.append({"case": case, "error": str(exc)})

    evaluated = [item for item in results if "error" not in item]
    tp = sum(item["true_positive"] for item in evaluated)
    fp = sum(item["false_positive"] for item in evaluated)
    fn = sum(item["false_negative"] for item in evaluated)
    accepted_fn = sum(item["accepted_false_negative"] for item in evaluated)
    model_fp = sum(
        item["model_generated_candidate"]
        for item in evaluated
        if not item["case"]["should_extract"]
    )
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "base_url": args.base_url,
        "model": "qwen2.5:3b-instruct",
        "dataset": args.dataset,
        "case_count": len(cases),
        "metrics": {
            "true_positive": tp,
            "false_positive": fp,
            "false_negative": fn,
            "accepted_false_negative": accepted_fn,
            "model_generated_false_positive": model_fp,
            "precision": precision,
            "recall": recall,
            "f1": (2 * precision * recall / (precision + recall)) if precision + recall else 0.0,
        },
        "results": results,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(
        json.dumps({"case_count": len(cases), "metrics": report["metrics"], "output": str(output)})
    )
    return 0 if len(evaluated) == len(cases) else 1


if __name__ == "__main__":
    raise SystemExit(main())
