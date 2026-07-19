"""Tests for K3 dossier copy brief."""

from internal.learning.dpick_copy import attach_brief_to_daily_pick, build_dpick_brief


def test_hold_candidate_brief_actionable():
    payload = {
        "action": "HOLD",
        "reason": "Confidence 23% below 45% audit gate — no long call published",
        "pick": None,
        "candidate": {
            "subnet": {"netuid": 99, "name": "SN99"},
            "final_confidence": 0.23,
            "reasons": ["Stochastic %K 98.1 (overbought)"],
            "audit": {
                "concerns": [
                    "Subnet flagged as overvalued",
                    "Thin volume: $1,200 < $5k",
                ]
            },
        },
        "time_horizon": "24h",
        "shortlist": [
            {
                "netuid": 40,
                "name": "Chunking",
                "conviction": 31,
                "role": "Higher emission but thinner liquidity",
            }
        ],
    }
    brief = build_dpick_brief(payload)
    assert brief["tone"] == "wait"
    assert "WAIT" in brief["move"]
    assert "SN99" in brief["move"]
    assert "23%" in brief["thesis"]
    assert "45%" in brief["thesis"]
    assert "Chunking" in brief["vs"]
    assert "Passed" in brief["vs"]


def test_audited_pick_brief_go():
    payload = {
        "action": "LONG",
        "pick": {
            "subnet": {"netuid": 14, "name": "TaoHash"},
            "final_confidence": 0.62,
            "reasons": ["Oversold RSI cluster on 4h"],
            "audit": {"concerns": []},
        },
        "time_horizon": "24h",
        "shortlist": [],
    }
    brief = build_dpick_brief(payload)
    assert brief["tone"] == "go"
    assert "SIZE IN" in brief["move"]
    assert "TaoHash" in brief["move"]


def test_attach_brief_on_payload():
    out = attach_brief_to_daily_pick({"action": "HOLD", "pick": None, "candidate": None})
    assert "brief" in out
    assert out["brief"]["move"]
