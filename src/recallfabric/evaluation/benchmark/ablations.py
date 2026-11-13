"""Ablation benchmark runner disabling each RecallFabric component to measure its contribution."""

from recallfabric.embeddings.service import EmbeddingProvider
from recallfabric.evaluation.benchmark.models import AblationResult
from recallfabric.evaluation.metrics import (
    calculate_conflict_accuracy,
    calculate_hallucination_rate,
    calculate_memory_efficiency,
    exact_match_score,
    is_conflict_resolved_correctly,
    is_hallucinated,
    precision_at_k,
    recall_at_k,
)
from recallfabric.evaluation.models import Conversation
from recallfabric.evaluation.systems.recallfabric_system import RecallFabricMemorySystem
from recallfabric.providers.base import LLMProvider

ABLATION_CONFIGS = [
    {
        "name": "full",
        "description": "Full RecallFabric pipeline (all components active)",
        "enable_ranking": True,
        "enable_dedupe": True,
        "enable_conflicts": True,
        "enable_extraction_filters": True,
    },
    {
        "name": "no_ranking",
        "description": "Ranking disabled: unweighted cosine similarity retrieval",
        "enable_ranking": False,
        "enable_dedupe": True,
        "enable_conflicts": True,
        "enable_extraction_filters": True,
    },
    {
        "name": "no_dedupe",
        "description": "Deduplication disabled: duplicate memories stored",
        "enable_ranking": True,
        "enable_dedupe": False,
        "enable_conflicts": True,
        "enable_extraction_filters": True,
    },
    {
        "name": "no_conflicts",
        "description": "Conflict resolution disabled: outdated contradictory facts retained",
        "enable_ranking": True,
        "enable_dedupe": True,
        "enable_conflicts": False,
        "enable_extraction_filters": True,
    },
    {
        "name": "no_extraction_filters",
        "description": "Extraction filters bypassed: conversational chatter & distractors stored",
        "enable_ranking": True,
        "enable_dedupe": True,
        "enable_conflicts": True,
        "enable_extraction_filters": False,
    },
]


def run_ablation_benchmarks(
    conversations: list[Conversation],
    llm: LLMProvider,
    embedder: EmbeddingProvider,
) -> dict[str, AblationResult]:
    """Execute ablation experiments across the 5 component configurations."""
    results: dict[str, AblationResult] = {}

    for cfg in ABLATION_CONFIGS:
        system = RecallFabricMemorySystem(
            llm=llm,
            embedder=embedder,
            enable_ranking=cfg["enable_ranking"],
            enable_dedupe=cfg["enable_dedupe"],
            enable_conflicts=cfg["enable_conflicts"],
            enable_extraction_filters=cfg["enable_extraction_filters"],
        )

        precisions = []
        recalls = []
        exact_matches = []
        hallucinations = []
        conflicts = []
        memories_per_conv = []
        dupe_counts = []
        distractors_stored = []
        total_distractors = []

        for conv in conversations:
            user_id = conv.user_id
            system.reset(user_id)
            c_distractors = 0

            for sess in conv.sessions:
                for turn in sess.turns:
                    if turn.role == "user":
                        if turn.is_distractor:
                            c_distractors += 1
                        system.ingest(
                            user_id=user_id,
                            message=turn.content,
                            fact_id=turn.fact_id,
                            fact_content=turn.fact_content,
                            is_distractor=turn.is_distractor,
                            is_update=turn.is_update,
                            session_id=sess.session_id,
                        )

            total_distractors.append(c_distractors)
            memories_per_conv.append(len(system.get_stored_memories(user_id)))
            dupe_counts.append(system.get_duplicate_count(user_id))
            distractors_stored.append(system.get_distractors_stored(user_id))

            for q in conv.questions:
                ans = system.answer(
                    user_id=user_id, question_id=q.question_id, question=q.question, k=5
                )
                p1 = precision_at_k(ans.retrieved_memory_ids, q.expected_memory_ids, k=1)
                r1 = recall_at_k(ans.retrieved_memory_ids, q.expected_memory_ids, k=1)
                em = exact_match_score(ans.reply, q.expected_answer, q.acceptable_answers)
                halluc = is_hallucinated(
                    ans.reply,
                    q.contradicted_answers,
                    q.expected_answer,
                    len(q.expected_memory_ids) == 0,
                )

                precisions.append(p1)
                recalls.append(r1)
                exact_matches.append(em)
                hallucinations.append(halluc)

                if q.is_conflict_test:
                    conf_ok = is_conflict_resolved_correctly(
                        ans.reply, q.latest_fact, q.superseded_fact
                    )
                    conflicts.append(conf_ok)

        eff = calculate_memory_efficiency(
            memories_per_conv=memories_per_conv,
            duplicate_counts=dupe_counts,
            distractors_stored=distractors_stored,
            total_distractors=total_distractors,
        )

        avg_p1 = sum(precisions) / float(len(precisions)) if precisions else 0.0
        avg_r1 = sum(recalls) / float(len(recalls)) if recalls else 0.0
        avg_em = sum(exact_matches) / float(len(exact_matches)) if exact_matches else 0.0
        halluc_rate = calculate_hallucination_rate(hallucinations)
        conflict_acc = calculate_conflict_accuracy(conflicts)

        results[cfg["name"]] = AblationResult(
            ablation_name=cfg["name"],
            description=cfg["description"],
            precision_at_1=round(avg_p1, 4),
            recall_at_1=round(avg_r1, 4),
            exact_match=round(avg_em, 4),
            hallucination_rate=round(halluc_rate, 4),
            conflict_accuracy=round(conflict_acc, 4),
            avg_memories_per_conv=eff["avg_memories_per_conv"],
            distractor_rejection_rate=eff["distractor_rejection_rate"],
        )

    return results
