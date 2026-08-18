"""Hero spotlight swaps bearish expert tails for judge-long desk leads."""

from __future__ import annotations

from internal.council.publish_gate import directional_publish_guard
from internal.learning.dpick_spotlight import attach_hero_spotlight_candidate
from internal.simivision.weighing_room import shape_weighing_board


def test_spotlight_replaces_bearish_expert_candidate(monkeypatch):
    expert = {
        "subnet": {"netuid": 13, "name": "Data Universe"},
        "final_confidence": 0.58,
        "signal_impact": {"net_direction": "bearish", "net_predicted_pct": -0.58},
    }
    assert directional_publish_guard(expert)["approved"] is False

    monkeypatch.setattr(
        "internal.simivision.weighing_room._judge_long_rows",
        lambda subnets, limit=1: [
            {
                "netuid": 25,
                "name": "Mainframe",
                "conviction": 89,
                "judge_scores": {
                    "oracle": {"score": 0.9, "confidence": 0.9},
                    "echo": {"score": 0.85, "confidence": 0.85},
                    "pulse": {"score": 0.8, "confidence": 0.8},
                },
            }
        ],
    )
    payload = {
        "action": "HOLD",
        "pick": None,
        "candidate": expert,
        "reason": "Directional conflict: council signal is bearish; no LONG published.",
    }
    out = attach_hero_spotlight_candidate(payload)
    assert out["hero_spotlight_source"] == "judge_long"
    assert out["candidate"]["subnet"]["netuid"] == 25
    assert out["desk_candidate"]["subnet"]["netuid"] == 13


def test_spotlight_keeps_nonconflicting_candidate(monkeypatch):
    expert = {
        "subnet": {"netuid": 4, "name": "Targon"},
        "final_confidence": 0.72,
        "signal_impact": {"net_direction": "bullish", "net_predicted_pct": 0.4},
    }
    monkeypatch.setattr(
        "internal.simivision.weighing_room._judge_long_rows",
        lambda subnets, limit=1: [{"netuid": 25, "name": "Mainframe", "conviction": 89}],
    )
    out = attach_hero_spotlight_candidate(
        {"action": "HOLD", "pick": None, "candidate": expert}
    )
    assert out["candidate"]["subnet"]["netuid"] == 4
    assert "hero_spotlight_source" not in out


def test_spotlight_uses_payload_reason_when_signal_impact_missing(monkeypatch):
    monkeypatch.setattr(
        "internal.simivision.weighing_room._judge_long_rows",
        lambda subnets, limit=12: [
            {"netuid": 0, "name": "Root", "conviction": 99},
            {"netuid": 25, "name": "Mainframe", "conviction": 89, "judge_scores": {}},
        ],
    )
    payload = {
        "action": "HOLD",
        "pick": None,
        "reason": "Directional conflict: council signal is bearish; no LONG published.",
        "candidate": {
            "subnet": {"netuid": 13, "name": "Data Universe"},
            "final_confidence": 0.58,
        },
    }
    out = attach_hero_spotlight_candidate(payload, [{"netuid": 25, "name": "Mainframe"}])
    assert out["hero_spotlight_source"] == "judge_long"
    assert out["candidate"]["subnet"]["netuid"] == 25
    assert out["desk_candidate"]["subnet"]["netuid"] == 13


def test_shape_board_no_false_stitch_without_call_context():
    top = [
        {
            "netuid": 25,
            "name": "Mainframe",
            "conviction": 89,
            "judge_long": True,
            "why_not": "Judge consensus 89%",
        }
    ]
    rows, meta = shape_weighing_board(top, pool_count=10, daily_pick=None)
    assert meta["call_netuid"] is None
    assert rows[0]["netuid"] == 25
    assert rows[0].get("closest_to_call") is not True


def test_shape_board_primary_call_gets_todays_call_stitch():
    daily = {
        "action": "HOLD",
        "pick": None,
        "candidate": {
            "subnet": {"netuid": 13, "name": "Data Universe"},
            "final_confidence": 0.58,
        },
    }
    top = [
        {
            "netuid": 25,
            "name": "Mainframe",
            "conviction": 89,
            "judge_long": True,
        }
    ]
    rows, meta = shape_weighing_board(top, pool_count=10, daily_pick=daily)
    assert meta["call_netuid"] == 13
    primary = next(r for r in rows if r.get("primary_call"))
    assert primary["netuid"] == 13
    assert primary["closest_to_call"] is True
    mainframe = next(r for r in rows if r["netuid"] == 25)
    assert mainframe.get("closest_to_call") is not True
