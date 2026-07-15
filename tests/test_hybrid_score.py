"""§16.2 — data-gated hybrid_score."""

from __future__ import annotations

from internal.council.grading import (
    HYBRID_MIN_SAMPLE,
    hybrid_score,
    hybrid_score_status,
    magnitude_calibration,
)


def test_magnitude_calibration_perfect_and_capped():
    assert magnitude_calibration(5.0, 5.0) == 1.0
    assert magnitude_calibration(0.0, 10.0) == 0.0
    assert magnitude_calibration(0.0, 20.0) == 0.0


def test_hybrid_score_none_below_gate():
    pred = {"direction": "up", "predicted_pct": 3.0}
    assert hybrid_score(pred, 2.5, sample_n=0) is None
    assert hybrid_score(pred, 2.5, sample_n=HYBRID_MIN_SAMPLE - 1) is None


def test_hybrid_score_float_when_gated_ok():
    pred = {"direction": "up", "predicted_pct": 3.0}
    score = hybrid_score(pred, 3.0, sample_n=HYBRID_MIN_SAMPLE)
    assert score is not None
    assert 0.0 <= score <= 1.0
    # perfect direction + perfect magnitude → 1.0
    assert score == 1.0

    miss = hybrid_score({"direction": "up", "predicted_pct": 3.0}, -3.0, sample_n=50)
    assert miss is not None
    assert miss < 0.5  # direction wrong


def test_hybrid_score_status_reason():
    status = hybrid_score_status(min_sample=10_000)
    assert status["ready"] is False
    assert status["reason"] == "not_enough_data"
    assert status["message"] == "not enough data yet"
