"""Command line interface for the memory accuracy benchmark."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sqlalchemy.exc import SQLAlchemyError

from .reporting import write_report
from .runner import DATASET_DIR, RESULTS_DIR, run_benchmark
from .validator import DatasetValidationError, validate_dataset


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="RecallFabric memory accuracy benchmark")
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser("validate", help="validate both frozen dataset splits")
    validate.add_argument("--dataset-dir", type=Path, default=DATASET_DIR)

    run = subparsers.add_parser("run", help="run production components in disposable schemas")
    run.add_argument("--split", choices=["development", "evaluation", "all"], default="development")
    run.add_argument("--mode", choices=["replay", "end-to-end", "retrieval-only"], default="replay")
    run.add_argument("--scenario", action="append", dest="scenario_ids")
    run.add_argument("--category")
    run.add_argument("--limit", type=int)
    run.add_argument("--env-file", type=Path)
    run.add_argument("--resume", action="store_true")
    run.add_argument(
        "--confirm-disposable-local-db",
        action="store_true",
        help=(
            "required acknowledgement that uniquely prefixed local schemas may be "
            "created and removed"
        ),
    )

    report = subparsers.add_parser(
        "report", help="regenerate aggregate artifacts from results JSONL"
    )
    report.add_argument("run_id")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "validate":
            development, evaluation = validate_dataset(args.dataset_dir)
            print(f"valid: {len(development)} development + {len(evaluation)} evaluation = 200")
            return 0
        if args.command == "report":
            output_dir = RESULTS_DIR / args.run_id
            manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
            results = [
                json.loads(line)
                for line in (output_dir / "results.jsonl").read_text(encoding="utf-8").splitlines()
                if line
            ]
            aggregate = write_report(output_dir, manifest, results)
            print(json.dumps(aggregate, indent=2))
            return 0
        output_dir, aggregate = run_benchmark(
            split=args.split,
            mode=args.mode,
            scenario_ids=args.scenario_ids,
            category=args.category,
            limit=args.limit,
            env_file=args.env_file,
            confirmed=args.confirm_disposable_local_db,
            resume=args.resume,
        )
        print(f"artifacts: {output_dir}")
        print(json.dumps(aggregate, indent=2))
        return 0 if aggregate["scenarios"]["failed"] == 0 else 2
    except (DatasetValidationError, ValueError, RuntimeError, OSError, SQLAlchemyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
