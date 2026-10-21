import math
from datetime import datetime

from recallfabric.core.config import Settings
from recallfabric.schemas.memory import ScoreBreakdown


def calculate_recency(created_at: datetime | None, now: datetime, half_life_days: float) -> float:
    if created_at is None:
        return 1.0
    if created_at.tzinfo is None and now.tzinfo is not None:
        created_at = created_at.replace(tzinfo=now.tzinfo)
    elif created_at.tzinfo is not None and now.tzinfo is None:
        now = now.replace(tzinfo=created_at.tzinfo)

    age_seconds = max(0.0, (now - created_at).total_seconds())
    age_days = age_seconds / 86400.0

    if half_life_days <= 0.0:
        return 0.0

    recency = 2.0 ** (-age_days / half_life_days)
    return max(0.0, min(1.0, recency))


def calculate_frequency(access_count: int, frequency_cap: int) -> float:
    if access_count <= 0:
        return 0.0
    if frequency_cap <= 0:
        return 1.0

    clamped_count = min(access_count, frequency_cap)
    frequency = math.log1p(clamped_count) / math.log1p(frequency_cap)
    return max(0.0, min(1.0, frequency))


def calculate_score(
    relevance: float,
    importance: float,
    confidence: float,
    recency: float,
    frequency: float,
    settings: Settings,
) -> tuple[float, ScoreBreakdown]:
    rel = max(0.0, min(1.0, relevance))
    imp = max(0.0, min(1.0, importance))
    conf = max(0.0, min(1.0, confidence))
    rec = max(0.0, min(1.0, recency))
    freq = max(0.0, min(1.0, frequency))

    score = (
        settings.rank_w_relevance * rel
        + settings.rank_w_importance * imp
        + settings.rank_w_confidence * conf
        + settings.rank_w_recency * rec
        + settings.rank_w_frequency * freq
    )
    breakdown = ScoreBreakdown(
        relevance=rel,
        importance=imp,
        confidence=conf,
        recency=rec,
        frequency=freq,
    )
    return score, breakdown
