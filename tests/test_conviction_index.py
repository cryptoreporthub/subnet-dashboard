"""Behavior tests for Telegram Conviction Index engine (11 tests)."""

from __future__ import annotations

import math

import pytest

from internal.conviction_index import (
    author_weight,
    compute_index,
    decay_factor,
    get_conviction_snapshot,
    momentum_sign,
    populate_author_reliability,
    signed_strength,
    weighted_median,
)


def _msg(
    conviction: float,
    direction_sign: int,
    *,
    calls: int = 0,
    correct: int = 0,
    age_hours: float = 0.0,
    predicted_timeframe: str = "24h",
) -> dict:
    return {
        "conviction": conviction,
        "direction_sign": direction_sign,
        "calls": calls,
        "correct": correct,
        "age_hours": age_hours,
        "predicted_timeframe": predicted_timeframe,
    }


def test_validated_new_caller_conviction_ladder():
    """New caller modest/mid/high bull + symmetric bear validated numbers."""
    modest = compute_index([_msg(60, 1)])
    assert modest["index"] == pytest.approx(54.0, abs=0.15)

    mid = compute_index([_msg(75, 1)])
    assert mid["index"] == pytest.approx(56.9, abs=0.35)

    high_bull = compute_index([_msg(95, 1)])
    assert high_bull["index"] == pytest.approx(62.5, abs=0.5)

    high_bear = compute_index([_msg(95, -1)])
    assert high_bear["index"] == pytest.approx(37.5, abs=0.5)


def test_validated_proven_caller_high_conviction():
  proven = compute_index([_msg(95, 1, calls=5, correct=4)])
  assert proven["index"] == pytest.approx(64.0, abs=0.1)


def test_validated_mixed_new_and_proven_bulls():
    msgs = [_msg(95, 1, calls=0, correct=0)] + [
        _msg(60, 1, calls=10, correct=6, age_hours=0.0) for _ in range(3)
    ]
    out = compute_index(msgs)
    assert out["index"] == pytest.approx(63.5, abs=0.2)
    assert out["confidence_pct"] == pytest.approx(61.0, abs=3.0)


def test_validated_hot_subnet():
    msgs = [
        _msg(90, 1, calls=15, correct=11, age_hours=1.0, predicted_timeframe="24h")
        for _ in range(4)
    ]
    out = compute_index(msgs)
    assert out["index"] == pytest.approx(75.5, abs=0.5)
    assert out["direction"] == "bullish"
    assert out["confidence_pct"] == pytest.approx(65.0, abs=3.0)


def test_validated_divergent_mix_neutral():
    msgs = [
        _msg(93, 1, calls=12, correct=7, age_hours=2.0),
        _msg(87, -1, calls=12, correct=7, age_hours=2.0),
    ]
    out = compute_index(msgs)
    assert out["index"] == pytest.approx(51.4, abs=0.2)
    assert out["direction"] == "neutral"


def test_validated_one_loud_unproven_caller():
    out = compute_index([_msg(97.8, 1, calls=0, correct=0)])
    assert out["index"] == pytest.approx(63.9, abs=0.1)
    assert out["confidence_pct"] == pytest.approx(29.0, abs=2.0)
    assert out["new_voice"] is True


def test_validated_modest_older_chatter():
    out = compute_index([_msg(79, 1, calls=0, correct=0, age_hours=13.0)])
    assert out["index"] == pytest.approx(56.2, abs=0.1)
    assert out["confidence_pct"] == pytest.approx(20.0, abs=3.0)


def test_symmetric_fade_matches_long_magnitude():
    long_side = compute_index([_msg(95, 1, calls=0, correct=0)])
    fade_side = compute_index([_msg(95, -1, calls=0, correct=0)])
    assert long_side["index"] - 50 == pytest.approx(50 - fade_side["index"], abs=0.1)


def test_low_confidence_flagged_not_hidden():
    empty = compute_index([])
    assert empty["flagged"] is True
    assert empty["new_voice"] is True
    assert "new voice" in empty["note"]

    quiet = compute_index([_msg(55, 1, calls=0, correct=0)])
    assert quiet["flagged"] is True
    assert quiet["index"] > 50


def test_decay_half_life_and_primitives():
    assert decay_factor(24.0) == pytest.approx(0.5, abs=0.01)
    assert decay_factor(0.0) == 1.0
    assert 0.0 < decay_factor(72.0) < 0.2

    assert signed_strength(100, 1) > 0
    assert signed_strength(100, -1) < 0
    assert signed_strength(100, 0) == 0.0
    assert signed_strength(50, 1) < 0.5
    assert signed_strength(90, 1) > signed_strength(30, 1)

    assert weighted_median([1, 2, 3], [1, 1, 1]) in (1, 2, 3)
    assert weighted_median([], []) == 0.0

    assert author_weight(0, 0) == 0.5
    assert author_weight(0, 0) > 0


def test_direction_from_momentum_not_verdict_label():
    """Guard historical BUY-tag-with-negative-prediction bug."""
    sign = momentum_sign("fade", momentum=-0.8)
    assert sign == -1
    sign2 = momentum_sign("BUY", momentum=-1.0)
    assert sign2 == -1
    assert momentum_sign("buy", momentum=0.5) == 1


def test_conviction_snapshot_refresh_uses_persisted_state(tmp_path, monkeypatch):
    state_path = tmp_path / "conviction_index.json"
    monkeypatch.setenv("CONVICTION_INDEX_PATH", str(state_path))
    from internal import conviction_index as ci

    ci._INDEX_PATH = str(state_path)
    monkeypatch.setattr(ci, "populate_author_reliability", lambda *a, **k: {"ok": True})
    state_path.write_text(
        '{"subnets": {"7": {"index": 66.0}}, "leaderboard": {"id:u1": {"author_id": "id:u1", "author_name": "Alice", "long_total": 3, "fade_total": 2, "long_hits": 2, "fade_hits": 1}}, "updated_at": "2026-08-01T00:00:00+00:00"}',
        encoding="utf-8",
    )

    snapshot = get_conviction_snapshot(refresh=True)
    assert snapshot["subnets"]["7"]["index"] == 66.0
    assert snapshot["leaderboard"]["id:u1"]["author_name"] == "Alice"


def test_conviction_leaderboard_marks_low_sample_caution(tmp_path, monkeypatch):
    state_path = tmp_path / "conviction_index.json"
    monkeypatch.setenv("CONVICTION_INDEX_PATH", str(state_path))
    from internal import conviction_index as ci

    ci._INDEX_PATH = str(state_path)
    state_path.write_text(
        '{"subnets": {}, "leaderboard": {"id:u1": {"author_id": "id:u1", "author_name": "Alice", "long_total": 1, "fade_total": 2, "long_hits": 1, "fade_hits": 0}}, "updated_at": null}',
        encoding="utf-8",
    )

    board = ci.build_leaderboard(days=30)
    assert board["authors"][0]["total_calls"] == 3
    assert board["authors"][0]["low_confidence"] is True
    assert board["authors"][0]["new_voice"] is False
