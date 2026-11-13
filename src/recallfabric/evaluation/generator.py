"""Deterministic generator for synthetic multi-session evaluation conversations."""

import json
import random
from pathlib import Path
from typing import Any

from recallfabric.evaluation.models import Conversation, Question, Session, Turn


def load_seeds(seed_path: str | Path | None = None) -> dict[str, Any]:
    if seed_path is None:
        seed_path = Path("evaluation/data/seeds.json")
    seed_file = Path(seed_path)
    if not seed_file.exists():
        # Fallback to relative from capstone root
        seed_file = Path(__file__).resolve().parents[3] / "evaluation" / "data" / "seeds.json"
    if not seed_file.exists():
        raise FileNotFoundError(f"Seeds file not found at {seed_path} or {seed_file}")
    with open(seed_file, encoding="utf-8") as f:
        return json.load(f)


def generate_conversations(
    count: int = 50,
    seed: int = 42,
    seeds_data: dict[str, Any] | None = None,
) -> list[Conversation]:
    rng = random.Random(seed)
    if seeds_data is None:
        seeds_data = load_seeds()

    domains = seeds_data.get("domains", [])
    stable_facts = seeds_data.get("stable_facts", [])
    distractors = seeds_data.get("distractors", [])
    distractor_questions = seeds_data.get("distractor_questions", [])

    conversations: list[Conversation] = []

    for idx in range(count):
        conv_id = f"conv_{idx + 1:03d}"
        user_id = f"eval_user_{idx + 1:03d}"

        # Choose 1 or 2 conflict domains deterministically
        num_domains = 1 if idx % 3 == 0 else 2
        selected_domains = rng.sample(domains, k=min(num_domains, len(domains)))

        # Choose 1 stable fact
        selected_stable = rng.choice(stable_facts)

        # Build Session 1: initial facts + 1 distractor
        sess1_turns: list[Turn] = []
        domain_updates = []

        for _d_idx, dom in enumerate(selected_domains):
            fact_key = dom["fact_key"]
            # Pick a pair
            pair_key = [k for k in dom.keys() if k.endswith("_pairs")][0]
            pairs = dom[pair_key]
            pair = pairs[idx % len(pairs)]
            val_a, val_b, extra_feature = pair[0], pair[1], pair[2]

            initial_tmpl = dom["initial"]
            msg_initial = (
                initial_tmpl["user_message"]
                .replace(f"{{{pair_key.split('_')[0]}_a}}", val_a)
                .replace("{city_a}", val_a)
                .replace("{diet_a}", val_a)
                .replace("{lang_a}", val_a)
                .replace("{company_a}", val_a)
                .replace("{drink_a}", val_a)
            )
            fact_content_initial = (
                initial_tmpl["fact_content"]
                .replace("{city_a}", val_a)
                .replace("{diet_a}", val_a)
                .replace("{lang_a}", val_a)
                .replace("{company_a}", val_a)
                .replace("{drink_a}", val_a)
            )

            fact_id_init = f"{conv_id}_fact_{fact_key}_v1"
            sess1_turns.append(
                Turn(
                    role="user",
                    content=msg_initial,
                    fact_id=fact_id_init,
                    fact_content=fact_content_initial,
                    is_distractor=False,
                    is_update=False,
                )
            )

            # Store update details for session 2
            update_tmpl = dom["update"]
            msg_update = (
                update_tmpl["user_message"]
                .replace("{city_b}", val_b)
                .replace("{diet_b}", val_b)
                .replace("{lang_b}", val_b)
                .replace("{company_b}", val_b)
                .replace("{drink_b}", val_b)
            )
            fact_content_update = (
                update_tmpl["fact_content"]
                .replace("{city_b}", val_b)
                .replace("{diet_b}", val_b)
                .replace("{lang_b}", val_b)
                .replace("{company_b}", val_b)
                .replace("{drink_b}", val_b)
            )
            q_info = dom["question"]
            q_text = q_info["text"]
            q_expected = (
                q_info["expected"]
                .replace("{city_b}", val_b)
                .replace("{diet_b}", val_b)
                .replace("{lang_b}", val_b)
                .replace("{company_b}", val_b)
                .replace("{drink_b}", val_b)
            )
            q_acceptable = [
                a.replace("{city_b}", val_b)
                .replace("{diet_b}", val_b)
                .replace("{lang_b}", val_b)
                .replace("{company_b}", val_b)
                .replace("{drink_b}", val_b)
                for a in q_info["acceptable"]
            ]
            q_contradicted = [
                c.replace("{city_a}", val_a)
                .replace("{diet_a}", val_a)
                .replace("{lang_a}", val_a)
                .replace("{company_a}", val_a)
                .replace("{drink_a}", val_a)
                for c in q_info["contradicted"]
            ]

            domain_updates.append(
                {
                    "fact_key": fact_key,
                    "msg_update": msg_update,
                    "fact_content_update": fact_content_update,
                    "fact_id_init": fact_id_init,
                    "fact_id_update": f"{conv_id}_fact_{fact_key}_v2",
                    "val_a": val_a,
                    "val_b": val_b,
                    "extra_feature": extra_feature,
                    "distractor_tmpl": dom.get("distractor", ""),
                    "q_text": q_text,
                    "q_expected": q_expected,
                    "q_acceptable": q_acceptable,
                    "q_contradicted": q_contradicted,
                }
            )

        # Add stable fact to Session 1
        stable_fact_id = f"{conv_id}_fact_{selected_stable['fact_key']}"
        sess1_turns.append(
            Turn(
                role="user",
                content=selected_stable["user_message"],
                fact_id=stable_fact_id,
                fact_content=selected_stable["fact_content"],
                is_distractor=False,
                is_update=False,
            )
        )

        # Add distractor chatter in Session 1
        distractor_1 = rng.choice(distractors)
        sess1_turns.append(
            Turn(
                role="user",
                content=distractor_1,
                is_distractor=True,
                is_update=False,
            )
        )

        session_1 = Session(session_id="sess_01", turns=sess1_turns)

        # Build Session 2: changed facts + domain distractor
        sess2_turns: list[Turn] = []
        questions: list[Question] = []

        for d_up in domain_updates:
            sess2_turns.append(
                Turn(
                    role="user",
                    content=d_up["msg_update"],
                    fact_id=d_up["fact_id_update"],
                    fact_content=d_up["fact_content_update"],
                    is_distractor=False,
                    is_update=True,
                    supersedes_fact_id=d_up["fact_id_init"],
                )
            )
            # Add domain distractor
            if d_up["distractor_tmpl"]:
                domain_dist = (
                    d_up["distractor_tmpl"]
                    .replace("{transit_feature}", d_up["extra_feature"])
                    .replace("{grocery_comment}", d_up["extra_feature"])
                    .replace("{editor_event}", d_up["extra_feature"])
                    .replace("{coffee_status}", d_up["extra_feature"])
                    .replace("{mug_status}", d_up["extra_feature"])
                )
                sess2_turns.append(
                    Turn(
                        role="user",
                        content=domain_dist,
                        is_distractor=True,
                        is_update=False,
                    )
                )

            # Create conflict test question
            questions.append(
                Question(
                    question_id=f"{conv_id}_q_conflict_{d_up['fact_key']}",
                    question=d_up["q_text"],
                    expected_memory_ids=[d_up["fact_id_update"]],
                    expected_answer=d_up["q_expected"],
                    acceptable_answers=d_up["q_acceptable"],
                    contradicted_answers=d_up["q_contradicted"],
                    is_conflict_test=True,
                    latest_fact=d_up["val_b"],
                    superseded_fact=d_up["val_a"],
                )
            )

        # Add another general distractor to Session 2
        distractor_2 = rng.choice(distractors)
        sess2_turns.append(
            Turn(
                role="user",
                content=distractor_2,
                is_distractor=True,
                is_update=False,
            )
        )

        session_2 = Session(session_id="sess_02", turns=sess2_turns)

        # Question for stable fact
        questions.append(
            Question(
                question_id=f"{conv_id}_q_stable_{selected_stable['fact_key']}",
                question=selected_stable["question"],
                expected_memory_ids=[stable_fact_id],
                expected_answer=selected_stable["expected"],
                acceptable_answers=selected_stable["acceptable"],
                contradicted_answers=selected_stable["contradicted"],
                is_conflict_test=False,
                latest_fact=selected_stable["expected"],
                superseded_fact=None,
            )
        )

        # Question for distractor (should reject memory / not hallucinate)
        dist_q = distractor_questions[idx % len(distractor_questions)]
        questions.append(
            Question(
                question_id=f"{conv_id}_q_distractor",
                question=dist_q["question"],
                expected_memory_ids=[],
                expected_answer=dist_q["expected"],
                acceptable_answers=dist_q["acceptable"],
                contradicted_answers=dist_q["contradicted"],
                is_conflict_test=False,
                latest_fact=None,
                superseded_fact=None,
            )
        )

        conversations.append(
            Conversation(
                conversation_id=conv_id,
                user_id=user_id,
                sessions=[session_1, session_2],
                questions=questions,
            )
        )

    return conversations


def generate_dataset_file(
    output_path: str | Path = "evaluation/data/dataset.jsonl",
    count: int = 50,
    seed: int = 42,
    seed_path: str | Path | None = None,
) -> Path:
    out_file = Path(output_path)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    seeds_data = load_seeds(seed_path)
    conversations = generate_conversations(count=count, seed=seed, seeds_data=seeds_data)

    with open(out_file, "w", encoding="utf-8") as f:
        for conv in conversations:
            f.write(json.dumps(conv.model_dump(), ensure_ascii=False) + "\n")

    return out_file
