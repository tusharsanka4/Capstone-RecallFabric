import json
from pathlib import Path

from recallfabric.core.config import Settings
from recallfabric.extraction.filters import filter_candidate
from recallfabric.extraction.prompt import SYSTEM_PROMPT
from tools.evaluate_live_extraction import evaluate_case

DATASET = Path(__file__).parents[1] / "evaluation" / "data" / "extraction_quality.jsonl"


def load_cases() -> list[dict]:
    return [json.loads(line) for line in DATASET.read_text(encoding="utf-8").splitlines()]


def test_extraction_quality_corpus_is_complete_and_balanced():
    cases = load_cases()
    assert len(cases) == 30
    assert sum(case["should_extract"] for case in cases) == 23
    assert sum(not case["should_extract"] for case in cases) == 7
    assert {case["category"] for case in cases} >= {
        "preference",
        "project",
        "skill",
        "goal",
        "career",
        "multiple",
        "temporary",
        "irrelevant",
        "ambiguous",
    }


def test_extraction_quality_corpus_has_unique_ids_and_ground_truth():
    cases = load_cases()
    ids = [case["case_id"] for case in cases]
    assert len(ids) == len(set(ids))
    for case in cases:
        assert case["text"].strip()
        assert isinstance(case["expected_keywords"], list)
        assert isinstance(case["should_extract"], bool)


def test_quality_filter_keeps_valid_third_person_facts():
    settings = Settings(_env_file=None, environment="test")
    valid, reason = filter_candidate(
        "User prefers concise technical explanations", 0.72, 0.85, settings
    )
    assert valid is True
    assert reason is None


def test_quality_filter_rejects_temporary_and_non_third_person_candidates():
    settings = Settings(_env_file=None, environment="test")
    temporary, temporary_reason = filter_candidate(
        "User is currently commuting home", 0.8, 0.9, settings
    )
    malformed, malformed_reason = filter_candidate(
        "The user is building RecallFabric", 0.8, 0.9, settings
    )
    assert temporary is False
    assert temporary_reason == "Content is a temporary or situational statement"
    assert malformed is False
    assert malformed_reason == "Fact must be in third person starting with 'User'"


def test_quality_filter_rejects_model_paraphrase_of_temporary_source():
    settings = Settings(_env_file=None, environment="test")
    valid, reason = filter_candidate(
        "User is waiting for a delivery",
        0.8,
        0.9,
        settings,
        source_text="I am currently waiting for a delivery.",
    )
    assert valid is False
    assert reason == "Source describes a temporary or situational activity"


def test_extraction_prompt_preserves_meaningful_qualifiers_and_intent():
    for phrase in (
        "with code examples",
        "browser extension",
        "legacy service",
        "publish a paper",
        "memory systems",
        "Preserve explicit intent verbs",
    ):
        assert phrase in SYSTEM_PROMPT


def test_evaluation_accepts_multiple_atomic_candidates_for_one_case():
    case = {
        "case_id": "multi",
        "text": "I prefer concise answers and I use Python every day.",
        "expected_keywords": ["prefer", "concise", "python"],
        "should_extract": True,
    }
    result = evaluate_case(
        case,
        {
            "status_code": 201,
            "body": {
                "candidates": [
                    {"content": "User prefers concise answers"},
                    {"content": "User uses Python every day"},
                ],
                "rejected": [],
            },
        },
    )
    assert result["true_positive"] is True
    assert result["accepted_false_negative"] is False


def test_evaluation_counts_temporary_candidate_as_false_positive():
    case = {
        "case_id": "temporary",
        "text": "I am currently waiting for a delivery.",
        "expected_keywords": [],
        "should_extract": False,
    }
    result = evaluate_case(
        case,
        {
            "status_code": 201,
            "body": {
                "candidates": [{"content": "User is waiting for a delivery"}],
                "rejected": [],
            },
        },
    )
    assert result["false_positive"] is True
