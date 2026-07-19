"""Weighing Room shaping — Conviction Board LOCK self-check."""

from internal.simivision.weighing_room import (
    _near_call_strip,
    deliberation_state,
    proximity_to_call,
    shape_weighing_board,
)


def test_near_call_strip_uses_lock_clock_not_speculation():
    assert "tonight" not in _near_call_strip("momentum holds").lower()
    with_clock = _near_call_strip("split judges align", resolves_in="10h 42m")
    assert "10h 42m" in with_clock
    assert "Near the call bar" in with_clock
    assert "tonight" not in with_clock.lower()


def test_proximity_and_states():
    assert proximity_to_call(70, 78) == 92
    assert deliberation_state(90, 2) == "NEAR-CALL"
    assert deliberation_state(60, 0) == "WEIGHING"
    assert deliberation_state(40, -4) == "FADING"


def test_shape_excludes_daily_call_and_sorts_by_proximity():
    top = [
        {"netuid": 1, "name": "A", "conviction": 90, "reasons": ["strong"], "recommendation": "BUY"},
        {"netuid": 2, "name": "B", "conviction": 70, "reasons": ["split"], "recommendation": "HOLD"},
        {"netuid": 3, "name": "C", "conviction": 40, "reasons": ["weak"], "recommendation": "WATCH"},
    ]
    daily = {
        "pick": {
            "subnet": {"netuid": 1, "name": "A"},
            "final_confidence": 0.9,
        },
        "resolves_in": "10h 42m",
    }
    rows, meta = shape_weighing_board(
        top, pool_count=20, daily_pick=daily, updated_at="2026-07-19T12:00:00Z"
    )
    assert all(r["netuid"] != 1 for r in rows)
    assert rows[0]["closest_to_call"] is True
    assert rows[0]["proximity"] >= rows[-1]["proximity"]
    assert "pick-rank" not in str(rows)
    assert meta["handoff"] and "10h 42m" in meta["handoff"]
    assert meta["quiet_label"].startswith("2 on table")
    assert meta["gap_tick_pct"] == 90
    assert "BUY" not in {r.get("deliberation_state") for r in rows}
