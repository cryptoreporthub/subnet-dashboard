"""Weighing Room shaping — Conviction Board LOCK self-check."""

from internal.simivision.weighing_room import (
    _near_call_strip,
    build_weighing_candidates_from_shortlist,
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


def _sample_subnets():
    return [
        {
            "netuid": 1,
            "name": "Alpha",
            "price": 1.0,
            "volume": 10000,
            "price_change_24h": 2.0,
            "emission": 100,
            "apy": 12.0,
        },
        {
            "netuid": 2,
            "name": "Beta",
            "price": 0.5,
            "volume": 8000,
            "price_change_24h": 1.0,
            "emission": 80,
            "apy": 10.0,
        },
        {
            "netuid": 3,
            "name": "Gamma",
            "price": 0.2,
            "volume": 6000,
            "price_change_24h": -0.5,
            "emission": 60,
            "apy": 8.0,
        },
    ]


def test_shortlist_wire_builds_from_deliberation_alternatives():
    daily = {
        "pick": {
            "subnet": {"netuid": 1, "name": "Alpha"},
            "final_confidence": 0.78,
            "expert_contributions": {"quant": 0.4, "hype": 0.2},
            "audit": {"concerns": []},
        }
    }
    raw, total = build_weighing_candidates_from_shortlist(_sample_subnets(), daily, {})
    assert total >= 2
    assert len(raw) >= 2
    assert all(r["netuid"] != 1 for r in raw)
    assert raw[0].get("why_not") is not None or raw[0].get("conviction") is not None


def test_shortlist_wire_honest_empty_when_thin():
    raw, total = build_weighing_candidates_from_shortlist(
        [{"netuid": 1, "name": "Only"}], {"pick": None}, {}
    )
    assert raw == []
    assert total >= 0


def test_shortlist_wire_reason_on_shaped_rows():
    daily = {
        "pick": {
            "subnet": {"netuid": 1, "name": "Alpha"},
            "final_confidence": 0.78,
            "expert_contributions": {"quant": 0.4, "hype": 0.2},
            "audit": {"concerns": []},
        },
        "resolves_in": "6h",
    }
    raw, total = build_weighing_candidates_from_shortlist(_sample_subnets(), daily, {})
    rows, meta = shape_weighing_board(
        raw,
        pool_count=total,
        total_considered=total,
        daily_pick=daily,
    )
    assert rows
    assert rows[0]["reason"]
    assert meta["quiet_count"] >= 0
    assert all(r["netuid"] != 1 for r in rows)
