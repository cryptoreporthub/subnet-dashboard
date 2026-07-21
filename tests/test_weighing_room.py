"""Weighing Room shaping — Conviction Board LOCK self-check."""

from internal.simivision.weighing_room import (
    SPINE_WHISPER,
    _near_call_strip,
    build_weighing_candidates_from_shortlist,
    deliberation_state,
    expert_split_line,
    gap_whisper,
    peel_horizon_line,
    proximity_to_call,
    shape_weighing_board,
    subnet_graded_snippet,
    trigger_for_state,
)


def test_near_call_strip_uses_lock_clock_not_speculation():
    assert "tonight" not in _near_call_strip("momentum holds").lower()
    with_clock = _near_call_strip("split judges align", resolves_in="10h 42m")
    assert "10h 42m" in with_clock
    assert "Call likely if" in with_clock
    assert "locks in" in with_clock
    assert "tonight" not in with_clock.lower()


def test_proximity_and_states():
    assert proximity_to_call(70, 78) == 92
    assert deliberation_state(90, 2) == "NEAR-CALL"
    assert deliberation_state(60, 0) == "WEIGHING"
    assert deliberation_state(40, -4) == "FADING"


def test_expert_split_uses_council_labels_not_oracle():
    line = expert_split_line(
        {"quant": 0.41, "hype": 0.28, "dark_horse": 0.22, "technical": 0.31}
    )
    assert line is not None
    assert "Quant leads" in line
    assert "Oracle" not in line
    assert "Echo" not in line
    assert "Pulse" not in line
    assert expert_split_line({}) is None
    assert expert_split_line(None) is None
    split = expert_split_line({"quant": 0.41, "hype": 0.38, "technical": 0.31})
    assert split and "dissent" in split


def test_gap_whisper_absolute_distance():
    assert gap_whisper(78, 82) == "4 pts from the call bar"
    assert gap_whisper(80, 82) == "2 pts below today's call"
    assert gap_whisper(85, 82) == "3 pts above the call bar"
    assert gap_whisper(82, 82) == "At the call bar"
    assert gap_whisper(70, 82) == "Still short of the call bar"
    assert gap_whisper(95, 82) == "Still clear of the call bar"
    assert gap_whisper(70, None) is None


def test_trigger_and_horizon():
    assert "Clears the bar" in trigger_for_state("NEAR-CALL")
    assert "recovery" in trigger_for_state("FADING")
    line = peel_horizon_line(horizon="24h", resolves_in="6h")
    assert "graded on 24h" in line
    assert "locks in 6h" in line
    assert peel_horizon_line(horizon=None, resolves_in=None) is None


def test_track_record_honest_empty(monkeypatch):
    monkeypatch.setattr(
        "internal.learning.predictions_store.load_predictions",
        lambda: {"predictions": [], "resolved": []},
    )
    assert "No graded call" in subnet_graded_snippet(42)


def test_track_record_hit_with_n(monkeypatch):
    monkeypatch.setattr(
        "internal.learning.predictions_store.load_predictions",
        lambda: {
            "predictions": [],
            "resolved": [
                {
                    "netuid": 7,
                    "correct": True,
                    "actual_pct": 4.2,
                    "horizon_type": "day",
                    "outcome": "hit",
                },
                {
                    "netuid": 7,
                    "correct": False,
                    "actual_pct": -2.1,
                    "horizon_type": "day",
                    "outcome": "miss",
                },
                {
                    "netuid": 7,
                    "correct": True,
                    "actual_pct": 1.5,
                    "horizon_type": "day",
                    "outcome": "hit",
                },
            ],
        },
    )
    line = subnet_graded_snippet(7)
    assert "Hit" in line
    assert "2✓ / 1✗" in line


def test_shape_excludes_daily_call_and_sorts_by_proximity():
    top = [
        {"netuid": 1, "name": "A", "conviction": 90, "reasons": ["strong"], "recommendation": "BUY"},
        {
            "netuid": 2,
            "name": "B",
            "conviction": 70,
            "reasons": ["split"],
            "recommendation": "HOLD",
            "expert_contributions": {"quant": 0.5, "hype": 0.3},
        },
        {"netuid": 3, "name": "C", "conviction": 40, "reasons": ["weak"], "recommendation": "WATCH"},
    ]
    daily = {
        "pick": {
            "subnet": {"netuid": 1, "name": "A"},
            "final_confidence": 0.9,
        },
        "resolves_in": "10h 42m",
        "time_horizon": "24h",
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
    assert meta["spine_whisper"] == SPINE_WHISPER
    assert "BUY" not in {r.get("deliberation_state") for r in rows}
    # stitch + gap whisper
    assert rows[0]["gap_whisper"]
    assert rows[0]["stitch_border"] is True
    assert rows[0]["mud_band"] in ("near", "watching")
    assert rows[0]["band_label"] in ("NEAR A CALL", "WATCHING")
    # peel receipts
    assert "Quant leads" in (rows[0].get("expert_split") or "")
    assert rows[0].get("track_record")
    assert rows[0].get("horizon_line") and "24h" in rows[0]["horizon_line"]
    assert "placeholder" not in str(rows).lower()


def test_fading_stitch_no_green_border():
    top = [
        {"netuid": 2, "name": "B", "conviction": 20, "recommendation": "WATCH"},
        {"netuid": 3, "name": "C", "conviction": 10, "recommendation": "WATCH"},
    ]
    daily = {
        "pick": {"subnet": {"netuid": 1, "name": "A"}, "final_confidence": 0.9},
        "resolves_in": "4h",
    }
    rows, _meta = shape_weighing_board(top, pool_count=10, daily_pick=daily)
    assert rows[0]["closest_to_call"] is True
    assert rows[0]["deliberation_state"] == "FADING"
    assert rows[0]["stitch_border"] is False
    assert rows[0]["mud_label"] == "WATCHING"
    assert rows[0]["band"] == "watching"


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
    # expert contributions passed through from shortlist
    assert isinstance(raw[0].get("expert_contributions"), dict)


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
    assert meta["spine_whisper"] == SPINE_WHISPER
