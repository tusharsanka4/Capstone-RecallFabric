"""Production-component runner for the memory accuracy benchmark."""

from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import NAMESPACE_URL, uuid5

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from recallfabric.api.chat import chat_endpoint
from recallfabric.api.extraction import MemoryExtractRequest, extract_chat_memories
from recallfabric.api.memories import retrieve_memories
from recallfabric.core.config import Settings
from recallfabric.db.models import Memory, MemoryEvent
from recallfabric.embeddings.service import create_embedding_provider
from recallfabric.extraction.decisions import DECISION_PROMPT
from recallfabric.extraction.prompt import SYSTEM_PROMPT
from recallfabric.memory_manager.events import record_event
from recallfabric.providers import get_chat_provider, get_extraction_provider
from recallfabric.schemas.chat import ChatMessage, ChatRequest
from recallfabric.schemas.memory import MemoryRetrieve
from recallfabric.security.encryption import decrypt_content

from .isolation import DisposableSchema, inspect_database
from .metrics import (
    acceptance_outcome,
    extraction_counts,
    provenance_outcome,
    reconciliation_outcome,
    retrieval_outcome,
)
from .reporting import write_report
from .validator import validate_dataset

REPO_ROOT = Path(__file__).resolve().parents[2]
DATASET_DIR = Path(__file__).resolve().parent / "dataset"
RESULTS_DIR = Path(__file__).resolve().parent / "results"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def dataset_hash(records: list[dict[str, Any]]) -> str:
    canonical = json.dumps(records, sort_keys=True, separators=(",", ":")).encode()
    return _sha256(canonical)


def _git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=REPO_ROOT, text=True, capture_output=True, check=False
    )
    return result.stdout.strip() if result.returncode == 0 else "unknown"


def _ollama_digest(settings: Settings) -> str | None:
    if (settings.extraction_provider or settings.llm_provider) != "ollama":
        return None
    try:
        url = settings.llm_base_url.removesuffix("/v1") + "/api/tags"
        models = httpx.get(url, timeout=2).json().get("models", [])
        match = next(
            (item for item in models if item.get("name") == settings.extraction_model), None
        )
        return match.get("digest") if match else None
    except Exception:
        return None


def build_manifest(
    settings: Settings,
    records: list[dict[str, Any]],
    *,
    run_id: str,
    mode: str,
    split: str,
    selection: dict[str, Any],
    database: dict[str, Any],
) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "started_at": datetime.now(UTC).isoformat(),
        "git": {"commit": _git("rev-parse", "HEAD"), "dirty": bool(_git("status", "--porcelain"))},
        "dataset_sha256": dataset_hash(records),
        "scenario_count": len(records),
        "mode": mode,
        "split": split,
        "selection": selection,
        "runtime": {"python": platform.python_version(), "os": platform.platform()},
        "provider": {
            "name": settings.extraction_provider or settings.llm_provider,
            "model": settings.extraction_model,
            "model_digest": _ollama_digest(settings),
            "temperature": settings.extraction_temperature,
            "timeout_seconds": settings.llm_timeout,
            "token_usage": "provider does not expose usage through current abstraction",
        },
        "embedding": {"provider": settings.embedding_provider, "model": settings.embedding_model},
        "prompts": {
            "user_fact_sha256": _sha256(SYSTEM_PROMPT.encode()),
            "decision_sha256": _sha256(DECISION_PROMPT.encode()),
        },
        "database": database,
        "seeds": {"dataset": "reviewed deterministic corpus", "runner": 0},
        "safety": {"schema_prefix": "rfbench_", "public_data_guard": True},
    }


def load_settings(env_file: str | Path | None = None) -> Settings:
    selected = Path(env_file) if env_file else (REPO_ROOT / ".env.local")
    kwargs: dict[str, Any] = {
        "environment": "test",
        "auth_enabled": False,
        "run_migrations": False,
    }
    if selected.exists():
        base = REPO_ROOT / ".env"
        kwargs["_env_file"] = (base, selected) if base.exists() and selected != base else selected
    return Settings(**kwargs)


def select_records(
    *,
    split: str,
    scenario_ids: list[str] | None = None,
    category: str | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    development, evaluation = validate_dataset(DATASET_DIR)
    records = (
        development + evaluation
        if split == "all"
        else (development if split == "development" else evaluation)
    )
    if scenario_ids:
        wanted = set(scenario_ids)
        records = [item for item in records if item["id"] in wanted]
        missing = wanted - {item["id"] for item in records}
        if missing:
            raise ValueError(f"Unknown scenario IDs in selected split: {sorted(missing)}")
    if category:
        records = [item for item in records if item["category"] == category]
    return records[:limit] if limit is not None else records


def deterministic_run_id(records: list[dict[str, Any]], mode: str) -> str:
    material = f"{dataset_hash(records)}:{mode}:{','.join(item['id'] for item in records)}"
    return _sha256(material.encode())[:12]


def _request(settings: Settings) -> Any:
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(settings=settings)))


def _predictions(session: Session, user_id: str, settings: Settings) -> list[dict[str, Any]]:
    rows = (
        session.execute(
            select(Memory)
            .where(Memory.user_id == user_id)
            .order_by(Memory.created_at, Memory.version)
        )
        .scalars()
        .all()
    )
    encryption_key = settings.encryption_key.get_secret_value() if settings.encryption_key else None
    return [
        {
            "id": str(row.id),
            "version": row.version,
            "previous_version": row.previous_version,
            "content": decrypt_content(row.content, encryption_key)
            if encryption_key
            else row.content,
            "type": row.type,
            "status": row.status,
            "source": row.source,
            "creation_reason": row.creation_reason,
            "metadata": row.attributes,
        }
        for row in rows
    ]


def _provenance(session: Session, user_id: str) -> list[dict[str, Any]]:
    events = (
        session.execute(
            select(MemoryEvent)
            .where(MemoryEvent.user_id == user_id)
            .order_by(MemoryEvent.created_at)
        )
        .scalars()
        .all()
    )
    return [
        {
            "memory_id": str(event.memory_id),
            "memory_version": event.memory_version,
            "event_type": event.event_type,
            "source": event.source,
            "actor": event.actor,
            "detail": event.detail,
        }
        for event in events
    ]


def _seed_retrieval_corpus(
    session: Session, scenario: dict[str, Any], user_id: str, embedder: Any
) -> None:
    active = [item for item in scenario["gold"]["memories"] if item["status"] == "active"]
    seeds = [(item["value"], item["type"], item["provenance"], item["id"]) for item in active]
    seeds.extend(
        (f"Unrelated benchmark distractor {index}", "other", "user", f"d{index}")
        for index in range(1, 13)
    )
    with session.begin():
        for content, kind, origin, stable_id in seeds:
            embedding = embedder.embed(content)
            row = Memory(
                id=uuid5(NAMESPACE_URL, f"{scenario['id']}:{stable_id}"),
                user_id=user_id,
                content=content,
                type=kind,
                importance=0.8,
                confidence=1.0,
                source=f"benchmark_retrieval_seed:{scenario['id']}",
                creation_reason="Retrieval-only benchmark seed",
                attributes={
                    "origin": origin,
                    "benchmark_gold_id": stable_id,
                    "retrieval_only_seed": True,
                },
                embedding=embedding.vector,
                embedding_model=embedding.model,
                embedding_dimensions=embedding.dimensions,
            )
            session.add(row)
            session.flush()
            record_event(
                session,
                user_id,
                row.id,
                "created",
                row.version,
                row.creation_reason,
                row.source,
                "benchmark",
            )


def _run_replay(
    scenario: dict[str, Any],
    session: Session,
    settings: Settings,
    embedder: Any,
    provider: Any,
    user_id: str,
) -> tuple[list[float], list[dict[str, str]]]:
    history: list[ChatMessage] = []
    latencies: list[float] = []
    for message in scenario["messages"]:
        if message["role"] == "user":
            if session.in_transaction():
                session.rollback()
            started = time.perf_counter()
            extract_chat_memories(
                MemoryExtractRequest(
                    user_id=user_id, text=message["content"], source=f"benchmark:{scenario['id']}"
                ),
                session,
                embedder,
                provider,
                _request(settings),
                None,
                history.copy(),
            )
            latencies.append((time.perf_counter() - started) * 1000)
        history.append(ChatMessage.model_validate(message))
    return latencies, [item.model_dump() for item in history]


def _run_end_to_end(
    scenario: dict[str, Any],
    session: Session,
    settings: Settings,
    embedder: Any,
    provider: Any,
    user_id: str,
) -> tuple[list[float], list[dict[str, str]]]:
    history: list[ChatMessage] = []
    latencies: list[float] = []
    for message in scenario["messages"]:
        if message["role"] != "user":
            continue
        if session.in_transaction():
            session.rollback()
        started = time.perf_counter()
        response = chat_endpoint(
            ChatRequest(
                user_id=user_id,
                message=message["content"],
                history=history.copy(),
                conversation_id=scenario["id"],
                extract=True,
            ),
            session,
            embedder,
            provider,
            _request(settings),
            None,
        )
        latencies.append((time.perf_counter() - started) * 1000)
        history.extend(
            [
                ChatMessage(role="user", content=message["content"]),
                ChatMessage(role="assistant", content=response.reply),
            ]
        )
    return latencies, [item.model_dump() for item in history]


def run_scenario(
    scenario: dict[str, Any],
    *,
    settings: Settings,
    run_id: str,
    mode: str,
    confirmed: bool,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "scenario_id": scenario["id"],
        "category": scenario["category"],
        "split": scenario["split"],
        "mode": mode,
        "error": None,
    }
    started = time.perf_counter()
    try:
        with DisposableSchema(settings, run_id, scenario["id"], confirmed=confirmed) as engine:
            embedder = create_embedding_provider(settings)
            provider = (
                get_chat_provider(settings)
                if mode == "end-to-end"
                else get_extraction_provider(settings)
            )
            user_id = f"benchmark_{scenario['id']}"
            with Session(engine) as session:
                if mode == "retrieval-only":
                    _seed_retrieval_corpus(session, scenario, user_id, embedder)
                    extraction_latencies: list[float] = []
                    conversation: list[dict[str, str]] = []
                elif mode == "replay":
                    extraction_latencies, conversation = _run_replay(
                        scenario, session, settings, embedder, provider, user_id
                    )
                else:
                    extraction_latencies, conversation = _run_end_to_end(
                        scenario, session, settings, embedder, provider, user_id
                    )
                if session.in_transaction():
                    session.rollback()
                predictions = _predictions(session, user_id, settings)
                provenance = _provenance(session, user_id)
                retrieval_metrics = []
                retrieval_records = []
                by_id = {item["id"]: item for item in scenario["gold"]["memories"]}
                for query in scenario["retrieval"]:
                    if session.in_transaction():
                        session.rollback()
                    query_started = time.perf_counter()
                    page = retrieve_memories(
                        MemoryRetrieve(
                            user_id=user_id, query=query["query"], limit=10, track_access=False
                        ),
                        session,
                        embedder,
                        _request(settings),
                        None,
                    )
                    query_latency = (time.perf_counter() - query_started) * 1000
                    returned = [item.model_dump(mode="json") for item in page.items]
                    targets = [by_id[mid] for mid in query["target_memory_ids"]]
                    query_metrics = retrieval_outcome(targets, returned)
                    query_metrics.update({"query_id": query["id"], "latency_ms": query_latency})
                    retrieval_metrics.append(query_metrics)
                    retrieval_records.append({"query": query, "returned": returned})
                if session.in_transaction():
                    session.rollback()
                active_count = int(
                    session.scalar(
                        select(func.count())
                        .select_from(Memory)
                        .where(Memory.user_id == user_id, Memory.status == "active")
                    )
                    or 0
                )

            expected = scenario["gold"]["memories"]
            result.update(
                {
                    "expected": scenario["gold"],
                    "predictions": predictions,
                    "provenance_events": provenance,
                    "conversation_used": conversation,
                    "retrieval": retrieval_records,
                    "active_memory_count": active_count,
                    "latencies_ms": {"extraction": extraction_latencies},
                    "metrics": {
                        "extraction": extraction_counts(expected, predictions),
                        "acceptance": acceptance_outcome(scenario, predictions),
                        "reconciliation": reconciliation_outcome(expected, predictions),
                        "provenance": provenance_outcome(expected, predictions),
                        "retrieval": retrieval_metrics,
                    },
                }
            )
    except Exception as exc:
        result["error"] = {"type": type(exc).__name__, "message": str(exc)}
        result.setdefault(
            "metrics",
            {
                "extraction": {"tp": 0, "fp": 0, "fn": len(scenario["gold"]["memories"])},
                "acceptance": {},
                "retrieval": [],
            },
        )
    result["elapsed_ms"] = (time.perf_counter() - started) * 1000
    return result


def run_benchmark(
    *,
    split: str = "development",
    mode: str = "replay",
    scenario_ids: list[str] | None = None,
    category: str | None = None,
    limit: int | None = None,
    env_file: str | Path | None = None,
    confirmed: bool = False,
    resume: bool = False,
) -> tuple[Path, dict[str, Any]]:
    if mode not in {"replay", "end-to-end", "retrieval-only"}:
        raise ValueError(f"Unsupported mode {mode!r}")
    records = select_records(split=split, scenario_ids=scenario_ids, category=category, limit=limit)
    if not records:
        raise ValueError("Selection contains no scenarios")
    settings = load_settings(env_file)
    database = inspect_database(settings, confirmed)
    run_id = deterministic_run_id(records, mode)
    output_dir = RESULTS_DIR / run_id
    output_dir.mkdir(parents=True, exist_ok=True)
    results_path = output_dir / "results.jsonl"
    results: list[dict[str, Any]] = []
    if resume and results_path.exists():
        results = [
            json.loads(line)
            for line in results_path.read_text(encoding="utf-8").splitlines()
            if line
        ]
    completed_ids = {item["scenario_id"] for item in results}
    selection = {"scenario_ids": scenario_ids, "category": category, "limit": limit}
    manifest = build_manifest(
        settings,
        records,
        run_id=run_id,
        mode=mode,
        split=split,
        selection=selection,
        database=database,
    )
    for scenario in records:
        if scenario["id"] in completed_ids:
            continue
        result = run_scenario(
            scenario, settings=settings, run_id=run_id, mode=mode, confirmed=confirmed
        )
        results.append(result)
        # Durable checkpoint after every scenario makes resume safe.
        write_report(output_dir, manifest, results)
    manifest["completed_at"] = datetime.now(UTC).isoformat()
    aggregate = write_report(output_dir, manifest, results)
    return output_dir, aggregate
