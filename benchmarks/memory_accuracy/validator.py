"""Strict validation for the frozen memory accuracy datasets."""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Iterable
from pathlib import Path
from typing import Any

CATEGORY_TOTALS = {
    "direct_user_facts": 25,
    "user_preferences_constraints": 20,
    "accepted_assistant_recommendations": 30,
    "rejected_assistant_recommendations": 20,
    "ambiguous_tentative_acceptance": 20,
    "partial_modified_acceptance": 20,
    "changed_decisions_supersession": 25,
    "hypotheticals_prompt_injection": 20,
    "long_context_cross_turn_references": 20,
}
DEVELOPMENT_TOTALS = {name: total // 5 for name, total in CATEGORY_TOTALS.items()}
REQUIRED_KEYS = {"id", "split", "category", "messages", "gold", "retrieval"}
SECRET_PATTERN = re.compile(
    r"(?:sk-[A-Za-z0-9]{20,}|AKIA[A-Z0-9]{16}|postgres(?:ql)?://[^\s]+:[^\s]+@|"
    r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----)"
)
ID_PATTERN = re.compile(r"^ma-[a-z0-9-]+-[0-9]{3}$")


class DatasetValidationError(ValueError):
    """Raised with all actionable dataset errors."""


def load_jsonl(path: str | Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as exc:
            raise DatasetValidationError(f"{path}:{line_number}: invalid JSON: {exc.msg}") from exc
        if not isinstance(item, dict):
            raise DatasetValidationError(f"{path}:{line_number}: scenario must be an object")
        records.append(item)
    return records


def _validate_record(item: dict[str, Any], location: str) -> list[str]:
    errors: list[str] = []
    missing = REQUIRED_KEYS - item.keys()
    extra = item.keys() - REQUIRED_KEYS
    if missing:
        errors.append(f"{location}: missing keys {sorted(missing)}")
    if extra:
        errors.append(f"{location}: unexpected keys {sorted(extra)}")
    scenario_id = item.get("id", "")
    if not isinstance(scenario_id, str) or not ID_PATTERN.fullmatch(scenario_id):
        errors.append(f"{location}: invalid stable id {scenario_id!r}")
    if item.get("split") not in {"development", "evaluation"}:
        errors.append(f"{location}: split must be development or evaluation")
    if item.get("category") not in CATEGORY_TOTALS:
        errors.append(f"{location}: unknown category {item.get('category')!r}")

    messages = item.get("messages")
    if not isinstance(messages, list) or not messages:
        errors.append(f"{location}: messages must be a nonempty list")
        messages = []
    for index, message in enumerate(messages):
        if not isinstance(message, dict) or set(message) != {"role", "content"}:
            errors.append(f"{location}: messages[{index}] requires only role and content")
            continue
        if message["role"] not in {"user", "assistant"}:
            errors.append(f"{location}: messages[{index}] has invalid role")
        if not isinstance(message["content"], str) or not message["content"].strip():
            errors.append(f"{location}: messages[{index}] content is blank")
    if messages and messages[0].get("role") != "user":
        errors.append(f"{location}: conversation must start with a user message")
    if any(messages[i].get("role") == messages[i - 1].get("role") for i in range(1, len(messages))):
        errors.append(f"{location}: adjacent messages must alternate roles")

    gold = item.get("gold")
    if not isinstance(gold, dict) or set(gold) != {"memories", "negative_memories", "acceptance"}:
        errors.append(f"{location}: gold requires memories, negative_memories, and acceptance")
        return errors
    memories = gold.get("memories", [])
    negatives = gold.get("negative_memories", [])
    if not isinstance(memories, list) or not isinstance(negatives, list):
        errors.append(f"{location}: gold memory lists are invalid")
        return errors
    memory_ids: set[str] = set()
    for index, memory in enumerate(memories):
        required = {
            "id",
            "persist",
            "subject",
            "value",
            "context",
            "type",
            "status",
            "provenance",
            "evidence",
        }
        if not isinstance(memory, dict) or not required.issubset(memory):
            errors.append(f"{location}: memories[{index}] is missing gold labels")
            continue
        if memory["id"] in memory_ids:
            errors.append(f"{location}: duplicate memory id {memory['id']!r}")
        memory_ids.add(memory["id"])
        if memory["persist"] is not True or memory["status"] not in {"active", "superseded"}:
            errors.append(f"{location}: memories[{index}] has invalid persist/status")
        for field in ("subject", "value", "context"):
            if not isinstance(memory[field], str) or not memory[field].strip():
                errors.append(f"{location}: memories[{index}].{field} is blank")
        if memory["type"] not in {"preference", "goal", "skill", "profile", "fact", "other"}:
            errors.append(f"{location}: memories[{index}] has invalid type")
        if memory["provenance"] not in {"user", "user_confirmed_assistant_recommendation"}:
            errors.append(f"{location}: memories[{index}] has invalid provenance")
        if not isinstance(memory["evidence"], list) or not memory["evidence"]:
            errors.append(f"{location}: memories[{index}] needs evidence")
        for quote in memory.get("evidence", []):
            if not any(quote in msg.get("content", "") for msg in messages):
                errors.append(f"{location}: evidence quote {quote!r} is absent from messages")
        supersedes = memory.get("supersedes")
        if supersedes is not None and supersedes not in memory_ids:
            # Forward references are checked after the loop.
            pass
    for memory in memories:
        if isinstance(memory, dict) and memory.get("supersedes") not in {None, *memory_ids}:
            errors.append(
                f"{location}: supersedes references unknown memory {memory.get('supersedes')!r}"
            )
    for index, negative in enumerate(negatives):
        if not isinstance(negative, dict) or set(negative) != {"value", "reason"}:
            errors.append(f"{location}: negative_memories[{index}] needs value and reason")
        elif not negative["value"].strip() or not negative["reason"].strip():
            errors.append(f"{location}: negative_memories[{index}] contains a blank field")

    acceptance = gold.get("acceptance")
    expected_acceptance_keys = {"required", "present", "proposal_accepted", "evidence"}
    if not isinstance(acceptance, dict) or set(acceptance) != expected_acceptance_keys:
        errors.append(f"{location}: invalid acceptance labels")
    else:
        label = acceptance["proposal_accepted"]
        if label not in {"yes", "no", "partial", "modified", "ambiguous", "not_applicable"}:
            errors.append(f"{location}: invalid proposal_accepted label")
        if acceptance["present"] and not acceptance["evidence"]:
            errors.append(f"{location}: present acceptance requires evidence")
        for quote in acceptance["evidence"]:
            if not any(quote in msg.get("content", "") for msg in messages):
                errors.append(f"{location}: acceptance evidence {quote!r} is absent")

    retrieval = item.get("retrieval")
    if not isinstance(retrieval, list):
        errors.append(f"{location}: retrieval must be a list")
    else:
        query_ids: set[str] = set()
        for index, query in enumerate(retrieval):
            if not isinstance(query, dict) or set(query) != {"id", "query", "target_memory_ids"}:
                errors.append(f"{location}: retrieval[{index}] is malformed")
                continue
            if not query["query"].strip() or query["id"] in query_ids:
                errors.append(f"{location}: retrieval[{index}] has blank query or duplicate id")
            query_ids.add(query["id"])
            unknown = set(query["target_memory_ids"]) - memory_ids
            if unknown:
                errors.append(
                    f"{location}: retrieval[{index}] references unknown memories {sorted(unknown)}"
                )
            inactive = {m["id"] for m in memories if m.get("status") != "active"} & set(
                query["target_memory_ids"]
            )
            if inactive:
                errors.append(
                    f"{location}: retrieval[{index}] targets inactive memories {sorted(inactive)}"
                )
    if SECRET_PATTERN.search(json.dumps(item)):
        errors.append(f"{location}: possible secret or credential detected")
    return errors


def validate_records(
    records: Iterable[dict[str, Any]], *, expected_split: str | None = None
) -> list[dict[str, Any]]:
    items = list(records)
    errors: list[str] = []
    seen: set[str] = set()
    for index, item in enumerate(items, 1):
        location = f"record {index} ({item.get('id', 'unknown')})"
        errors.extend(_validate_record(item, location))
        if item.get("id") in seen:
            errors.append(f"{location}: duplicate scenario id")
        seen.add(item.get("id"))
        if expected_split and item.get("split") != expected_split:
            errors.append(f"{location}: expected split {expected_split!r}")
    if errors:
        raise DatasetValidationError("Dataset validation failed:\n- " + "\n- ".join(errors))
    return items


def validate_dataset(dataset_dir: str | Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    root = Path(dataset_dir)
    development = validate_records(
        load_jsonl(root / "development.jsonl"), expected_split="development"
    )
    evaluation = validate_records(
        load_jsonl(root / "evaluation.jsonl"), expected_split="evaluation"
    )
    all_records = development + evaluation
    errors: list[str] = []
    if len(development) != 40 or len(evaluation) != 160 or len(all_records) != 200:
        errors.append(
            f"expected 40 development + 160 evaluation = 200; got "
            f"{len(development)} + {len(evaluation)} = {len(all_records)}"
        )
    if len({item["id"] for item in all_records}) != 200:
        errors.append("scenario IDs must be unique across both splits")
    total_counts = Counter(item["category"] for item in all_records)
    dev_counts = Counter(item["category"] for item in development)
    if total_counts != Counter(CATEGORY_TOTALS):
        errors.append(f"category totals mismatch: {dict(total_counts)}")
    if dev_counts != Counter(DEVELOPMENT_TOTALS):
        errors.append(f"development stratification mismatch: {dict(dev_counts)}")
    if errors:
        raise DatasetValidationError("Dataset validation failed:\n- " + "\n- ".join(errors))
    return development, evaluation
