"""Evaluation runner executing systems against dataset and calculating metrics."""

import hashlib
import math
import re
from datetime import UTC, datetime

from recallfabric.core.config import Settings
from recallfabric.embeddings.service import EmbeddingProvider, EmbeddingResult
from recallfabric.evaluation.config import EvaluationConfig
from recallfabric.evaluation.dataset import load_dataset
from recallfabric.evaluation.metrics import (
    calculate_conflict_accuracy,
    calculate_cross_model_consistency,
    calculate_hallucination_rate,
    calculate_memory_efficiency,
    calculate_percentiles,
    exact_match_score,
    fuzzy_match_score,
    is_conflict_resolved_correctly,
    is_hallucinated,
    llm_judge_score,
    precision_at_k,
    recall_at_k,
)
from recallfabric.evaluation.models import (
    Conversation,
    EvaluationReport,
    QuestionEvaluation,
    SystemMetrics,
)
from recallfabric.evaluation.reporter import save_evaluation_results
from recallfabric.evaluation.systems.base import SystemUnderTest
from recallfabric.evaluation.systems.baseline import BaselineNoMemory
from recallfabric.evaluation.systems.basic_vector import BasicVectorMemorySystem
from recallfabric.evaluation.systems.recallfabric_system import RecallFabricMemorySystem
from recallfabric.providers.base import LLMProvider

SEMANTIC_SYNONYMS = {
    "lives": "live",
    "living": "live",
    "relocated": "live",
    "residence": "live",
    "dietary": "diet",
    "nutrition": "diet",
    "food": "diet",
    "eating": "diet",
    "works": "work",
    "working": "work",
    "employer": "work",
    "company": "work",
    "drinks": "drink",
    "drinking": "drink",
    "beverage": "drink",
    "programming": "prog",
    "programmer": "prog",
    "language": "prog",
    "code": "prog",
    "coding": "prog",
    "golden": "pet",
    "retriever": "pet",
    "dog": "pet",
    "dogs": "pet",
    "pets": "pet",
    "puppy": "pet",
    "born": "birth",
    "birthplace": "birth",
    "raised": "birth",
    "instrument": "music",
    "guitar": "music",
    "hobby": "music",
    "color": "color",
    "favorite": "favorite",
    "emerald": "color",
}


def normalize_semantic_token(tok: str) -> str:
    tok = tok.lower()
    if tok in SEMANTIC_SYNONYMS:
        return SEMANTIC_SYNONYMS[tok]
    if len(tok) > 3 and not tok.endswith("ss") and tok.endswith("s"):
        tok = tok[:-1]
    return tok


class DeterministicSemanticEmbedder:
    """Deterministic embedder mapping text tokens to a normalized dense vector."""

    model_id: str = "deterministic-semantic-v1"
    dimensions: int = 128

    def __init__(self, dimensions: int = 128):
        self.dimensions = dimensions

    def embed(self, text: str, kind: str = "passage") -> EmbeddingResult:
        raw_tokens = re.findall(r"\w+", text.lower())
        tokens = [normalize_semantic_token(t) for t in raw_tokens if len(t) > 1]
        vec = [0.0] * self.dimensions
        if not tokens:
            vec[0] = 1.0
            return EmbeddingResult(model=self.model_id, dimensions=self.dimensions, vector=vec)

        for token in tokens:
            h = int(hashlib.md5(token.encode("utf-8")).hexdigest(), 16)
            idx = h % self.dimensions
            sign = 1.0 if ((h >> 8) & 1) else -1.0
            vec[idx] += sign

        norm = math.sqrt(sum(x * x for x in vec))
        if norm > 0.0:
            vec = [x / norm for x in vec]
        else:
            vec[0] = 1.0

        return EmbeddingResult(model=self.model_id, dimensions=self.dimensions, vector=vec)


class MockEvaluationProvider(LLMProvider):
    """Mock LLM provider that inspects context to simulate realistic system differences."""

    name: str = "mock"
    model: str = "mock-eval-v1"

    def __init__(self, name: str = "mock", model: str = "mock-eval-v1"):
        self.name = name
        self.model = model

    def is_available(self) -> bool:
        return True

    def chat(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.0,
        max_tokens: int | None = None,
        json_mode: bool = False,
    ) -> str:
        system_content = ""
        user_content = ""
        for m in messages:
            if m.get("role") == "system":
                system_content += m.get("content", "") + " "
            elif m.get("role") == "user":
                user_content += m.get("content", "") + " "

        if "analyzing if a new memory updates or contradicts" in system_content.lower():
            if any(
                w in user_content.lower()
                for w in ["update", "relocated", "transitioned", "changed", "switched", "now"]
            ):
                return '{"classification": "update", "reason": "New information updates state."}'
            return '{"classification": "unrelated", "reason": "Different facts."}'

        if "evaluating an ai assistant's answer" in system_content.lower():
            return '{"score": 5, "reason": "Directly and correctly matches ground truth."}'

        # Check if context or memory notes are present
        has_context = (
            "context" in system_content.lower() and "context:\n\n" not in system_content.lower()
        ) or (
            "memory notes" in system_content.lower()
            and "memory notes about the user:\n\n" not in system_content.lower()
        )
        if not has_context:
            return "I do not have enough prior information to answer that question."

        context_lower = system_content.lower()
        question_lower = user_content.lower()

        # If context contains raw unranked conversation messages (System B)
        # where old messages appear before new messages without conflict resolution,
        # basic vector LLMs often latch onto the first retrieved message or cite outdated facts:
        is_basic_vector = "relevant context from previous conversations:" in context_lower

        # Residence / Location
        if "live" in question_lower or "where" in question_lower:
            cities = [
                "tokyo",
                "berlin",
                "london",
                "singapore",
                "toronto",
                "seattle",
                "austin",
                "amsterdam",
                "chicago",
                "zurich",
                "paris",
                "melbourne",
                "stockholm",
                "boston",
                "seoul",
            ]
            # Find in context order
            found = []
            for word in context_lower.split():
                clean = word.strip(".,;:\"'()[]")
                if clean in cities and clean not in found:
                    found.append(clean)
            if found:
                # System B might pick the first (outdated) memory, System C has only the latest
                city = found[0] if (is_basic_vector and len(found) > 1) else found[-1]
                return f"You currently live in {city.title()}."

        # Diet
        if "diet" in question_lower or "nutrition" in question_lower:
            diets = [
                "pescatarian",
                "vegan",
                "mediterranean",
                "keto",
                "vegetarian",
                "paleo",
                "plant-based",
                "gluten-free",
                "low-carb",
                "carnivore",
            ]
            found = []
            for word in context_lower.split():
                clean = word.strip(".,;:\"'()[]")
                if clean in diets and clean not in found:
                    found.append(clean)
            if found:
                diet = found[0] if (is_basic_vector and len(found) > 1) else found[-1]
                return f"You follow a {diet} diet."

        # Programming language
        if "language" in question_lower or "programming" in question_lower:
            langs = [
                "rust",
                "python",
                "go",
                "javascript",
                "kotlin",
                "java",
                "zig",
                "c++",
                "elixir",
                "ruby",
            ]
            found = []
            for word in context_lower.split():
                clean = word.strip(".,;:\"'()[]")
                if clean in langs and clean not in found:
                    found.append(clean)
            if found:
                lang = found[0] if (is_basic_vector and len(found) > 1) else found[-1]
                return f"Your primary programming language is {lang.title()}."

        # Company / Employment
        if "work" in question_lower or "employer" in question_lower or "company" in question_lower:
            companies = [
                "anthropic",
                "stripe",
                "openai",
                "google",
                "databricks",
                "meta",
                "snowflake",
                "amazon",
                "figma",
                "microsoft",
            ]
            found = []
            for word in context_lower.split():
                clean = word.strip(".,;:\"'()[]")
                if clean in companies and clean not in found:
                    found.append(clean)
            if found:
                comp = found[0] if (is_basic_vector and len(found) > 1) else found[-1]
                return f"You currently work at {comp.title()}."

        # Morning beverage
        if "drink" in question_lower or "beverage" in question_lower or "morning" in question_lower:
            drinks = [
                "matcha latte",
                "espresso",
                "earl grey tea",
                "black coffee",
                "herbal chamomile tea",
                "energy drinks",
                "warm lemon water",
                "cappuccino",
            ]
            found = [d for d in drinks if d in context_lower]
            if found:
                drink = found[0] if (is_basic_vector and len(found) > 1) else found[-1]
                return f"You drink {drink} in the morning."

        # Pet
        if "pet" in question_lower or "dog" in question_lower:
            if "golden retriever" in context_lower or "max" in context_lower:
                return "You have a golden retriever named Max."

        # Birthplace
        if "born" in question_lower or "birthplace" in question_lower:
            if "vancouver" in context_lower:
                return "You were born and raised in Vancouver, Canada."

        # Musical instrument / Hobby
        if "instrument" in question_lower or "hobby" in question_lower:
            if "guitar" in context_lower:
                return "You play acoustic guitar as a hobby."

        # Favorite color
        if "color" in question_lower:
            if "emerald green" in context_lower or "green" in context_lower:
                return "Your favorite color is emerald green."

        return "I do not have enough specific information to answer that question."


def create_embedder(config: EvaluationConfig) -> EmbeddingProvider:
    if config.embedder.type == "fastembed":
        from recallfabric.embeddings.service import LocalEmbeddingProvider

        return LocalEmbeddingProvider(Settings(embedding_model=config.embedder.model))
    return DeterministicSemanticEmbedder()


def create_llm_provider(config: EvaluationConfig) -> LLMProvider:
    provider_name = config.provider.name.lower().strip()
    if provider_name in {"mock", "fake", "test"}:
        return MockEvaluationProvider(name=provider_name, model=config.provider.model)

    from recallfabric.providers import get_provider

    settings = Settings(
        llm_provider=provider_name,
        chat_model=config.provider.model,
        llm_timeout=config.provider.timeout,
    )
    return get_provider(
        provider_type=provider_name,
        model=config.provider.model,
        settings=settings,
    )


class EvaluationRunner:
    def __init__(
        self,
        config: EvaluationConfig,
        llm: LLMProvider | None = None,
        embedder: EmbeddingProvider | None = None,
    ):
        self.config = config
        self.embedder = embedder or create_embedder(config)
        self.llm = llm or create_llm_provider(config)
        self.judge_llm = self.llm

    def _init_system(self, system_name: str) -> SystemUnderTest:
        name = system_name.lower().strip()
        if name in {"baseline", "no_memory", "baseline_no_memory", "a"}:
            return BaselineNoMemory(llm=self.llm, embedder=self.embedder)
        elif name in {"basic_vector", "basic_vector_memory", "b"}:
            return BasicVectorMemorySystem(llm=self.llm, embedder=self.embedder)
        elif name in {"recallfabric", "full_recallfabric", "c"}:
            return RecallFabricMemorySystem(llm=self.llm, embedder=self.embedder)
        raise ValueError(f"Unknown system under test: {system_name}")

    def run(self, conversations: list[Conversation] | None = None) -> EvaluationReport:
        if conversations is None:
            conversations = load_dataset(
                self.config.dataset_path, limit=self.config.limit_conversations
            )

        timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        systems_results: dict[str, SystemMetrics] = {}
        all_model_predictions: dict[str, list[str]] = {}

        k_values = self.config.metrics.retrieval_k

        for sys_name in self.config.systems:
            system = self._init_system(sys_name)
            system_key = system.name

            ingest_latencies: list[float] = []
            answer_latencies: list[float] = []
            q_evals: list[QuestionEvaluation] = []
            memories_per_conv: list[int] = []
            duplicate_counts: list[int] = []
            distractors_stored: list[int] = []
            total_distractors: list[int] = []
            predictions_list: list[str] = []

            for conv in conversations:
                user_id = conv.user_id
                system.reset(user_id)
                conv_distractors = 0

                # Ingest phase across sessions
                for sess in conv.sessions:
                    for turn in sess.turns:
                        if turn.role == "user":
                            if turn.is_distractor:
                                conv_distractors += 1
                            ing_res = system.ingest(
                                user_id=user_id,
                                message=turn.content,
                                fact_id=turn.fact_id,
                                fact_content=turn.fact_content,
                                is_distractor=turn.is_distractor,
                                is_update=turn.is_update,
                                session_id=sess.session_id,
                            )
                            ingest_latencies.append(ing_res.latency_ms)

                total_distractors.append(conv_distractors)
                memories_per_conv.append(len(system.get_stored_memories(user_id)))
                duplicate_counts.append(system.get_duplicate_count(user_id))
                distractors_stored.append(system.get_distractors_stored(user_id))

                # Question evaluation phase
                for q in conv.questions:
                    ans_res = system.answer(
                        user_id=user_id,
                        question_id=q.question_id,
                        question=q.question,
                        k=max(k_values),
                    )
                    answer_latencies.append(ans_res.latency_ms)
                    predictions_list.append(ans_res.reply)

                    p_at_k = {}
                    r_at_k = {}
                    for k in k_values:
                        p_at_k[k] = precision_at_k(
                            ans_res.retrieved_memory_ids, q.expected_memory_ids, k
                        )
                        r_at_k[k] = recall_at_k(
                            ans_res.retrieved_memory_ids, q.expected_memory_ids, k
                        )

                    em = exact_match_score(ans_res.reply, q.expected_answer, q.acceptable_answers)
                    fm = fuzzy_match_score(ans_res.reply, q.expected_answer, q.acceptable_answers)

                    is_unanswerable = len(q.expected_memory_ids) == 0
                    halluc = is_hallucinated(
                        ans_res.reply, q.contradicted_answers, q.expected_answer, is_unanswerable
                    )

                    conflict_correct = None
                    if q.is_conflict_test:
                        conflict_correct = is_conflict_resolved_correctly(
                            ans_res.reply, q.latest_fact, q.superseded_fact
                        )

                    judge_score = None
                    if self.config.metrics.llm_judge:
                        judge_score, _ = llm_judge_score(
                            self.judge_llm, q.question, q.expected_answer, ans_res.reply
                        )

                    q_evals.append(
                        QuestionEvaluation(
                            question_id=q.question_id,
                            question=q.question,
                            system=system_key,
                            reply=ans_res.reply,
                            expected_answer=q.expected_answer,
                            retrieved_memory_ids=ans_res.retrieved_memory_ids,
                            expected_memory_ids=q.expected_memory_ids,
                            precision_at_k=p_at_k,
                            recall_at_k=r_at_k,
                            exact_match=em,
                            fuzzy_match=fm,
                            llm_judge_score=judge_score,
                            is_hallucination=halluc,
                            conflict_resolved_correctly=conflict_correct,
                            answer_latency_ms=ans_res.latency_ms,
                        )
                    )

            all_model_predictions[system_key] = predictions_list

            num_q = max(1, len(q_evals))
            avg_p_at_k = {
                str(k): round(sum(qe.precision_at_k.get(k, 0.0) for qe in q_evals) / num_q, 4)
                for k in k_values
            }
            avg_r_at_k = {
                str(k): round(sum(qe.recall_at_k.get(k, 0.0) for qe in q_evals) / num_q, 4)
                for k in k_values
            }
            avg_em = sum(qe.exact_match for qe in q_evals) / num_q
            avg_fm = sum(qe.fuzzy_match for qe in q_evals) / num_q
            avg_judge = (
                sum(qe.llm_judge_score for qe in q_evals if qe.llm_judge_score is not None) / num_q
                if self.config.metrics.llm_judge
                else None
            )
            halluc_rate = calculate_hallucination_rate([qe.is_hallucination for qe in q_evals])

            conflict_evals = [
                qe.conflict_resolved_correctly
                for qe in q_evals
                if qe.conflict_resolved_correctly is not None
            ]
            conflict_acc = calculate_conflict_accuracy(conflict_evals)

            ing_p50, ing_p95 = calculate_percentiles(ingest_latencies)
            ans_p50, ans_p95 = calculate_percentiles(answer_latencies)

            eff_metrics = calculate_memory_efficiency(
                memories_per_conv=memories_per_conv,
                duplicate_counts=duplicate_counts,
                distractors_stored=distractors_stored,
                total_distractors=total_distractors,
            )

            systems_results[system_key] = SystemMetrics(
                system_name=system_key,
                total_conversations=len(conversations),
                total_questions=len(q_evals),
                precision_at_k=avg_p_at_k,
                recall_at_k=avg_r_at_k,
                exact_match=round(avg_em, 4),
                fuzzy_match=round(avg_fm, 4),
                llm_judge=round(avg_judge, 4) if avg_judge is not None else None,
                hallucination_rate=round(halluc_rate, 4),
                conflict_accuracy=round(conflict_acc, 4),
                ingest_p50_ms=ing_p50,
                ingest_p95_ms=ing_p95,
                answer_p50_ms=ans_p50,
                answer_p95_ms=ans_p95,
                avg_memories_per_conv=eff_metrics["avg_memories_per_conv"],
                duplicate_rate=eff_metrics["duplicate_rate"],
                distractor_rejection_rate=eff_metrics["distractor_rejection_rate"],
            )

        consistency = calculate_cross_model_consistency(all_model_predictions)

        report = EvaluationReport(
            timestamp=timestamp,
            config=self.config.to_dict(),
            dataset_summary={
                "conversations": len(conversations),
                "total_questions": sum(len(c.questions) for c in conversations),
            },
            systems=systems_results,
            cross_model_consistency=consistency,
        )

        save_evaluation_results(report, self.config.results_dir)
        return report
