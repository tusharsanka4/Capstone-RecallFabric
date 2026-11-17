"""Contract tests for the 200-scenario memory accuracy benchmark."""

from __future__ import annotations

import copy
import json
from collections import Counter

import pytest

from benchmarks.memory_accuracy.cli import main
from benchmarks.memory_accuracy.isolation import assert_safe_target, safe_schema_name
from benchmarks.memory_accuracy.metrics import (
    acceptance_outcome,
    aggregate_results,
    extraction_counts,
    pair_memories,
    provenance_outcome,
    retrieval_outcome,
    wilson_interval,
)
from benchmarks.memory_accuracy.reporting import write_report
from benchmarks.memory_accuracy.runner import (
    DATASET_DIR,
    deterministic_run_id,
    run_scenario,
    select_records,
)
from benchmarks.memory_accuracy.validator import (
    CATEGORY_TOTALS,
    DEVELOPMENT_TOTALS,
    DatasetValidationError,
    validate_dataset,
    validate_records,
)
from recallfabric.core.config import Settings


@pytest.fixture(scope="module")
def corpus():
    return validate_dataset(DATASET_DIR)


def test_dataset_has_exact_distribution_and_stratified_split(corpus):
    development, evaluation = corpus
    assert (len(development), len(evaluation)) == (40, 160)
    assert Counter(row["category"] for row in development) == Counter(DEVELOPMENT_TOTALS)
    assert Counter(row["category"] for row in development + evaluation) == Counter(CATEGORY_TOTALS)
    assert len({row["id"] for row in development + evaluation}) == 200


def test_json_schema_is_checked_in_and_parseable():
    schema_path = DATASET_DIR.parent / "dataset_schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    assert schema["$schema"].endswith("2020-12/schema")
    assert set(schema["required"]) == {"id", "split", "category", "messages", "gold", "retrieval"}


def test_dataset_includes_zero_multi_supersession_and_retrieval_cases(corpus):
    rows = corpus[0] + corpus[1]
    assert any(not row["gold"]["memories"] for row in rows)
    assert any(len(row["gold"]["memories"]) > 1 for row in rows)
    assert any(
        any(memory["status"] == "superseded" for memory in row["gold"]["memories"]) for row in rows
    )
    assert any(len(row["retrieval"]) > 1 for row in rows)


@pytest.mark.parametrize(
    "mutation,fragment",
    [
        (lambda row: row.update(id="bad id"), "invalid stable id"),
        (lambda row: row["messages"].append({"role": "user", "content": "again"}), "alternate"),
        (
            lambda row: row["gold"]["acceptance"].update(present=True, evidence=[]),
            "requires evidence",
        ),
        (
            lambda row: row["retrieval"].append(
                {"id": "bad", "query": "x", "target_memory_ids": ["missing"]}
            ),
            "unknown memories",
        ),
        (
            lambda row: row["messages"][0].update(content="postgresql://admin:secret@localhost/db"),
            "secret",
        ),
    ],
)
def test_validator_rejects_corruption(corpus, mutation, fragment):
    row = copy.deepcopy(corpus[0][0])
    mutation(row)
    with pytest.raises(DatasetValidationError, match=fragment):
        validate_records([row], expected_split="development")


def test_cli_validation_and_selection(capsys):
    assert main(["validate"]) == 0
    assert "= 200" in capsys.readouterr().out
    selected = select_records(
        split="development", category="accepted_assistant_recommendations", limit=2
    )
    assert len(selected) == 2
    assert all(row["category"] == "accepted_assistant_recommendations" for row in selected)
    assert deterministic_run_id(selected, "replay") == deterministic_run_id(selected, "replay")


def test_database_guard_requires_opt_in_and_local_nonproduction():
    local = Settings(_env_file=None, database_url="postgresql+psycopg://u:p@127.0.0.1:5434/test")
    with pytest.raises(RuntimeError, match="--confirm"):
        assert_safe_target(local, False)
    assert assert_safe_target(local, True)["database"] == "test"
    remote = Settings(_env_file=None, database_url="postgresql+psycopg://u:p@example.com/test")
    with pytest.raises(RuntimeError, match="non-local"):
        assert_safe_target(remote, True)
    production = local.model_copy(update={"environment": "production"})
    with pytest.raises(RuntimeError, match="production"):
        assert_safe_target(production, True)


def test_schema_names_are_owned_and_bounded():
    name = safe_schema_name("123456789abc", "ma-direct-user-facts-001")
    assert name.startswith("rfbench_") and len(name) <= 63
    with pytest.raises(RuntimeError, match="Unsafe"):
        safe_schema_name("!", "!")


def _gold(value="PostgreSQL", status="active"):
    return {
        "id": "m1",
        "value": value,
        "subject": "database",
        "context": "database",
        "type": "fact",
        "status": status,
        "provenance": "user",
    }


def test_structured_matching_handles_multi_memory_and_extra_prediction():
    expected = [_gold(), {**_gold("Redis"), "id": "m2", "subject": "cache", "context": "cache"}]
    predicted = [
        {"content": "User selected PostgreSQL as the database", "type": "fact"},
        {"content": "Redis", "type": "fact"},
        {"content": "invented", "type": "fact"},
    ]
    matches, missed, extra = pair_memories(expected, predicted)
    assert len(matches) == 2 and not missed and extra == [2]
    assert extraction_counts(expected, predicted) == {
        "tp": 2,
        "fp": 1,
        "fn": 0,
        "precision": 2 / 3,
        "recall": 1.0,
        "f1": 0.8,
    }


def test_duplicate_prediction_is_counted_as_false_positive():
    expected = [_gold()]
    predicted = [
        {"content": "PostgreSQL", "type": "fact"},
        {"content": "User selected PostgreSQL", "type": "fact"},
    ]
    assert extraction_counts(expected, predicted)["fp"] == 1


def test_negative_case_and_acceptance_false_alarm():
    scenario = {"gold": {"acceptance": {"proposal_accepted": "no"}}}
    predicted = [{"metadata": {"origin": "user_confirmed_assistant_recommendation"}}]
    outcome = acceptance_outcome(scenario, predicted)
    assert outcome["false_acceptance"] and not outcome["correct"]
    assert extraction_counts([], predicted)["fp"] == 1


def test_confirmed_recommendation_provenance_requires_both_quotes():
    expected = [
        {
            **_gold(),
            "provenance": "user_confirmed_assistant_recommendation",
        }
    ]
    prediction = {
        "content": "User selected PostgreSQL as the database",
        "type": "fact",
        "metadata": {
            "origin": "user_confirmed_assistant_recommendation",
            "assistant_quote": "PostgreSQL",
            "acceptance_quote": "Let's use that.",
        },
    }
    assert provenance_outcome(expected, [prediction]) == {"eligible": 1, "correct": 1}
    del prediction["metadata"]["acceptance_quote"]
    assert provenance_outcome(expected, [prediction]) == {"eligible": 1, "correct": 0}


def test_retrieval_metrics_and_missing_targets():
    target = _gold()
    outcome = retrieval_outcome(
        [target], [{"content": "noise", "type": "fact"}, {"content": "PostgreSQL", "type": "fact"}]
    )
    assert outcome["recall_at_1"] == 0
    assert outcome["recall_at_5"] == 1
    assert outcome["mrr"] == 0.5
    assert retrieval_outcome([target], [])["success"] == 0


def test_zero_denominators_and_partial_results_are_defined():
    assert extraction_counts([], []) == {
        "tp": 0,
        "fp": 0,
        "fn": 0,
        "precision": 1.0,
        "recall": 1.0,
        "f1": 1.0,
    }
    assert wilson_interval(0, 0) == [None, None]
    partial = [
        {"scenario_id": "x", "category": "c", "error": {"type": "Timeout", "message": "timed out"}}
    ]
    summary = aggregate_results(partial)
    assert summary["scenarios"] == {"requested": 1, "completed": 0, "failed": 1}


def test_report_writes_required_artifacts(tmp_path):
    manifest = {
        "run_id": "abc",
        "mode": "replay",
        "split": "development",
        "git": {"commit": "deadbeef", "dirty": True},
    }
    result = {
        "scenario_id": "s",
        "category": "direct_user_facts",
        "error": None,
        "active_memory_count": 1,
        "latencies_ms": {"extraction": [10.0]},
        "metrics": {
            "extraction": {"tp": 1, "fp": 0, "fn": 0},
            "acceptance": {"correct": True, "false_acceptance": False, "missed_acceptance": False},
            "provenance": {"correct": 1, "eligible": 1},
            "reconciliation": {"statuses_correct": 1, "matched": 1, "obsolete_active": 0},
            "retrieval": [],
        },
    }
    write_report(tmp_path, manifest, [result])
    required = {
        "manifest.json",
        "results.jsonl",
        "aggregate_metrics.json",
        "category_metrics.csv",
        "failures.csv",
        "failures.jsonl",
        "REPORT.md",
    }
    assert required <= {path.name for path in tmp_path.iterdir()}
    assert json.loads((tmp_path / "aggregate_metrics.json").read_text())["extraction"]["tp"] == 1


def test_runner_records_timeout_and_invokes_schema_cleanup(monkeypatch, corpus):
    exited = []

    class FakeSchema:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return object()

        def __exit__(self, *args):
            exited.append(True)

    monkeypatch.setattr("benchmarks.memory_accuracy.runner.DisposableSchema", FakeSchema)
    monkeypatch.setattr(
        "benchmarks.memory_accuracy.runner.create_embedding_provider",
        lambda settings: (_ for _ in ()).throw(TimeoutError("provider timed out")),
    )
    result = run_scenario(
        corpus[0][0],
        settings=Settings(_env_file=None),
        run_id="123456789abc",
        mode="replay",
        confirmed=True,
    )
    assert result["error"] == {"type": "TimeoutError", "message": "provider timed out"}
    assert exited == [True]
