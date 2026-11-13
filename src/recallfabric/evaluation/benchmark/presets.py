"""Ranking weight preset benchmarks comparing relevance-only, default, and recency-heavy."""

from recallfabric.embeddings.service import EmbeddingProvider
from recallfabric.evaluation.benchmark.models import PresetResult
from recallfabric.evaluation.metrics import (
    calculate_conflict_accuracy,
    exact_match_score,
    fuzzy_match_score,
    is_conflict_resolved_correctly,
    precision_at_k,
    recall_at_k,
)
from recallfabric.evaluation.models import Conversation
from recallfabric.evaluation.systems.recallfabric_system import RecallFabricMemorySystem
from recallfabric.providers.base import LLMProvider

PRESET_CONFIGS = [
    {
        "name": "default",
        "description": "Balanced RecallFabric multi-factor ranking weights",
        "weights": {
            "w_relevance": 0.45,
            "w_importance": 0.20,
            "w_confidence": 0.15,
            "w_recency": 0.10,
            "w_frequency": 0.10,
        },
    },
    {
        "name": "relevance-only",
        "description": "Pure semantic relevance without temporal decay or importance",
        "weights": {
            "w_relevance": 1.00,
            "w_importance": 0.00,
            "w_confidence": 0.00,
            "w_recency": 0.00,
            "w_frequency": 0.00,
        },
    },
    {
        "name": "recency-heavy",
        "description": "Heavily biased toward newest memories with aggressive decay",
        "weights": {
            "w_relevance": 0.20,
            "w_importance": 0.10,
            "w_confidence": 0.05,
            "w_recency": 0.60,
            "w_frequency": 0.05,
        },
    },
]


def run_ranking_preset_benchmarks(
    conversations: list[Conversation],
    llm: LLMProvider,
    embedder: EmbeddingProvider,
) -> dict[str, PresetResult]:
    """Execute benchmarks comparing ranking weight presets."""
    results: dict[str, PresetResult] = {}

    for p_cfg in PRESET_CONFIGS:
        system = RecallFabricMemorySystem(
            llm=llm,
            embedder=embedder,
            enable_ranking=True,
            ranking_weights=p_cfg["weights"],
        )

        precisions = []
        recalls = []
        exact_matches = []
        fuzzy_matches = []
        conflicts = []

        for conv in conversations:
            user_id = conv.user_id
            system.reset(user_id)

            for sess in conv.sessions:
                for turn in sess.turns:
                    if turn.role == "user":
                        system.ingest(
                            user_id=user_id,
                            message=turn.content,
                            fact_id=turn.fact_id,
                            fact_content=turn.fact_content,
                            is_distractor=turn.is_distractor,
                            is_update=turn.is_update,
                            session_id=sess.session_id,
                        )

            for q in conv.questions:
                ans = system.answer(
                    user_id=user_id, question_id=q.question_id, question=q.question, k=5
                )
                p1 = precision_at_k(ans.retrieved_memory_ids, q.expected_memory_ids, k=1)
                r1 = recall_at_k(ans.retrieved_memory_ids, q.expected_memory_ids, k=1)
                em = exact_match_score(ans.reply, q.expected_answer, q.acceptable_answers)
                fm = fuzzy_match_score(ans.reply, q.expected_answer, q.acceptable_answers)

                precisions.append(p1)
                recalls.append(r1)
                exact_matches.append(em)
                fuzzy_matches.append(fm)

                if q.is_conflict_test:
                    conf_ok = is_conflict_resolved_correctly(
                        ans.reply, q.latest_fact, q.superseded_fact
                    )
                    conflicts.append(conf_ok)

        avg_p1 = sum(precisions) / float(len(precisions)) if precisions else 0.0
        avg_r1 = sum(recalls) / float(len(recalls)) if recalls else 0.0
        avg_em = sum(exact_matches) / float(len(exact_matches)) if exact_matches else 0.0
        avg_fm = sum(fuzzy_matches) / float(len(fuzzy_matches)) if fuzzy_matches else 0.0
        conflict_acc = calculate_conflict_accuracy(conflicts)

        results[p_cfg["name"]] = PresetResult(
            preset_name=p_cfg["name"],
            description=p_cfg["description"],
            weights=p_cfg["weights"],
            precision_at_1=round(avg_p1, 4),
            recall_at_1=round(avg_r1, 4),
            exact_match=round(avg_em, 4),
            fuzzy_match=round(avg_fm, 4),
            conflict_accuracy=round(conflict_acc, 4),
        )

    return results
