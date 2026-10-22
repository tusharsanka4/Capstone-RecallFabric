"""LLM-as-judge evaluation metric using the provider layer with a fixed rubric."""

import json

from recallfabric.providers.base import LLMProvider

DEFAULT_JUDGE_RUBRIC = (
    "You are an impartial judge evaluating an AI assistant's answer against ground truth facts.\n"
    "Rate the answer on a scale from 1 to 5 using the following criteria:\n"
    "- 5: Perfectly accurate and complete. Directly states facts without hallucination.\n"
    "- 4: Mostly accurate. Correctly conveys the core fact with minor phrasing variations.\n"
    "- 3: Partially correct. Contains some factual elements but is incomplete or imprecise.\n"
    "- 2: Mostly incorrect. Misses the key ground truth fact or gives vague guesses.\n"
    "- 1: Completely incorrect. Contradicts ground truth or asserts fabricated facts.\n\n"
    'Format your output strictly as a JSON object: {"score": <1-5>, "reason": "<explanation>"}'
)


def llm_judge_score(
    llm: LLMProvider,
    question: str,
    ground_truth: str,
    prediction: str,
    rubric: str = DEFAULT_JUDGE_RUBRIC,
) -> tuple[float, str]:
    """Score prediction using an LLM judge on a 0.0 to 1.0 scale."""
    user_prompt = (
        f"Question: {question}\nGround Truth: {ground_truth}\nCandidate Answer: {prediction}\n"
    )
    messages = [
        {"role": "system", "content": rubric},
        {"role": "user", "content": user_prompt},
    ]

    try:
        raw_response = llm.chat(messages=messages, temperature=0.0, json_mode=True)
        data = json.loads(raw_response)
        raw_score = float(data.get("score", 1.0))
        reason = str(data.get("reason", ""))
        # Clamp to [1, 5]
        clamped = max(1.0, min(5.0, raw_score))
        # Normalize 1..5 to 0.0..1.0
        normalized = (clamped - 1.0) / 4.0
        return normalized, reason
    except Exception as e:
        # Fallback heuristic if LLM judge fails or is mock
        return 0.0, f"Judge failed: {e}"
