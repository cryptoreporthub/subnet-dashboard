"""Tribunal derivation — split benches, gated HOLD, cold miss."""

from internal.learning.dpick_tribunal import (
    attach_tribunal_to_daily_pick,
    build_tribunal_block,
)


def test_sealed_buy_with_split_benches():
    payload = {
        "status": "ok",
        "date": "2026-08-03",
        "action": "LONG",
        "pick": {
            "subnet": {"netuid": 64, "name": "Chutes", "description": "Compute"},
            "final_confidence": 0.72,
            "action": "LONG",
            "expert_contributions": {
                "quant": 0.82,
                "hype": 0.20,
                "dark_horse": 0.55,
                "technical": 0.77,
            },
        },
        "resolves_in": "56m",
        "time_horizon": "1h",
    }
    t = build_tribunal_block(payload)
    assert t["verdict"] == "BUY"
    assert t["verdict_kind"] == "sealed"
    assert t["conviction_pct"] == 72
    assert t["case_id"] == "#SN64-0803"
    assert len(t["benches"]) == 4
    by_key = {b["key"]: b for b in t["benches"]}
    assert by_key["quant"]["stance"] == "BUY"
    assert by_key["hype"]["stance"] == "SELL"
    assert by_key["technical"]["stance"] == "BUY"
    assert t["spread"]["outlier_bench"] == "hype"
    assert t["spread"]["pts"] > 40
    assert t["concur"]["n"] == 2  # quant + technical (dark_horse HOLD)
    assert t["concur"]["of"] == 4


def test_gated_hold_uses_candidate():
    payload = {
        "status": "ok",
        "date": "2026-08-03",
        "action": "HOLD",
        "reason": "Confidence 34% below 40% audit gate — no long call published",
        "pick": None,
        "candidate": {
            "subnet": {"netuid": 99, "name": "Thirty Spokes"},
            "final_confidence": 0.34,
            "expert_contributions": {
                "quant": 0.50,
                "hype": 0.48,
                "dark_horse": 0.52,
                "technical": 0.49,
            },
        },
    }
    t = build_tribunal_block(payload)
    assert t["verdict"] == "HOLD"
    assert t["verdict_kind"] == "gated"
    assert t["gate"]["passed"] is False
    assert "audit gate" in t["gate"]["reason"]
    assert t["subnet"]["netuid"] == 99
    assert t["session_label"].startswith("Case open")


def test_cold_and_forming_degrade():
    assert build_tribunal_block(None)["verdict_kind"] == "cold"
    assert build_tribunal_block({})["verdict_kind"] == "cold"
    forming = build_tribunal_block({"status": "pending", "action": "HOLD"})
    assert forming["verdict_kind"] == "forming"
    assert forming["benches"] == []


def test_attach_never_raises():
    out = attach_tribunal_to_daily_pick({"action": "HOLD"})
    assert "tribunal" in out
    assert out["tribunal"]["verdict_kind"] in ("forming", "gated", "cold", "sealed")

    # Missing experts → forming with subnet still filled
    out2 = attach_tribunal_to_daily_pick(
        {
            "action": "LONG",
            "pick": {"subnet": {"netuid": 1, "name": "A"}, "final_confidence": 0.9},
        }
    )
    assert out2["tribunal"]["subnet"]["netuid"] == 1
    assert out2["tribunal"]["benches"] == []
