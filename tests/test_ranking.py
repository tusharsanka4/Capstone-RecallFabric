import math
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from recallfabric.core.config import Settings
from recallfabric.ranking.scoring import (
    calculate_frequency,
    calculate_recency,
    calculate_score,
)


def test_ranking_weights_sum_validation():
    s = Settings(_env_file=None)
    total = (
        s.rank_w_relevance
        + s.rank_w_importance
        + s.rank_w_confidence
        + s.rank_w_recency
        + s.rank_w_frequency
    )
    assert math.isclose(total, 1.0, rel_tol=1e-3)

    with pytest.raises(ValidationError):
        Settings(_env_file=None, rank_w_relevance=0.9, rank_w_importance=0.9)


def test_recency_decay_monotonic():
    now = datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC)
    half_life = 14.0

    r_now = calculate_recency(now, now, half_life)
    assert math.isclose(r_now, 1.0)

    t_7d = now - timedelta(days=7)
    r_7d = calculate_recency(t_7d, now, half_life)

    t_14d = now - timedelta(days=14)
    r_14d = calculate_recency(t_14d, now, half_life)
    assert math.isclose(r_14d, 0.5, rel_tol=1e-3)

    t_28d = now - timedelta(days=28)
    r_28d = calculate_recency(t_28d, now, half_life)
    assert math.isclose(r_28d, 0.25, rel_tol=1e-3)

    assert r_now > r_7d > r_14d > r_28d > 0.0

    future = now + timedelta(days=5)
    r_future = calculate_recency(future, now, half_life)
    assert math.isclose(r_future, 1.0)


def test_frequency_log_scaled_and_saturates():
    cap = 100

    f_0 = calculate_frequency(0, cap)
    assert f_0 == 0.0

    f_neg = calculate_frequency(-5, cap)
    assert f_neg == 0.0

    f_10 = calculate_frequency(10, cap)
    f_50 = calculate_frequency(50, cap)
    f_100 = calculate_frequency(100, cap)
    f_500 = calculate_frequency(500, cap)

    assert 0.0 < f_10 < f_50 < f_100
    assert math.isclose(f_100, 1.0)
    assert math.isclose(f_500, 1.0)


def test_combined_scoring_and_breakdown():
    settings = Settings(_env_file=None)
    score, breakdown = calculate_score(
        relevance=0.8,
        importance=0.9,
        confidence=1.0,
        recency=0.5,
        frequency=0.2,
        settings=settings,
    )

    expected = (
        settings.rank_w_relevance * 0.8
        + settings.rank_w_importance * 0.9
        + settings.rank_w_confidence * 1.0
        + settings.rank_w_recency * 0.5
        + settings.rank_w_frequency * 0.2
    )
    assert math.isclose(score, expected)
    assert 0.0 <= score <= 1.0
    assert breakdown.relevance == 0.8
    assert breakdown.importance == 0.9
    assert breakdown.confidence == 1.0
    assert breakdown.recency == 0.5
    assert breakdown.frequency == 0.2


def test_scoring_clamping():
    settings = Settings(_env_file=None)
    score, breakdown = calculate_score(
        relevance=1.5,
        importance=-0.5,
        confidence=2.0,
        recency=-1.0,
        frequency=1.2,
        settings=settings,
    )

    assert breakdown.relevance == 1.0
    assert breakdown.importance == 0.0
    assert breakdown.confidence == 1.0
    assert breakdown.recency == 0.0
    assert breakdown.frequency == 1.0
    assert 0.0 <= score <= 1.0
