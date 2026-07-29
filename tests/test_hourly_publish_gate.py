"""Hourly pick publish gate — HOLD below gate, long above, no learning pollution."""

from __future__ import annotations

from internal.council.hourly_pick import clear_hourly_pick_cache, select_hourly_pick
from internal.council.pick_scheduler import _record_hour_pick
from server import _highest_emission_pick, _record_pick_in_learning_loop


def _subnet(netuid: int = 1, **overrides) -> dict:
    row = {
        "netuid": netuid,
        "name": f"SN{netuid}",
        "symbol": f"SN{netuid}",
        "emission": 2.0,
        "price": 1.0,
        "volume": 5000,
        "price_change_24h": 1.0,
    }
    row.update(overrides)
    return row


def _stub_score_path(monkeypatch, adjusted_confidence: float):
    clear_hourly_pick_cache()

    def hour(sn, ctx):
        return {
            "total_score": 80.0,
            "confidence": adjusted_confidence,
            "expert_contributions": {},
            "scenario_tags": {},
        }

    monkeypatch.setattr("internal.council.hourly_pick.score_subnet_for_hour", hour)
    monkeypatch.setattr(
        "internal.council.hourly_pick.audit_daily_pick",
        lambda candidate, subnets: {
            "approved": adjusted_confidence >= 0.4,
            "concerns": [],
            "adjusted_confidence": adjusted_confidence,
        },
    )
    monkeypatch.setattr(
        "internal.council.hourly_pick.attach_council_prediction",
        lambda *args, **kwargs: {"statement": "test"},
    )
    monkeypatch.setattr(
        "internal.council.hourly_pick.unpack_score_learning_fields",
        lambda score: {
            "signal_impact": None,
            "signal_contributions": None,
            "active_signals": [],
        },
    )
    monkeypatch.setattr("internal.council.hourly_pick.pick_reasons", lambda *args: [])


def test_empty_subnets_returns_hold():
    clear_hourly_pick_cache()
    pick = select_hourly_pick([])
    assert pick["action"] == "HOLD"
    assert "No tradable" in (pick.get("hold_reason") or "")
    assert pick["subnet"] is None


def test_low_confidence_holds_with_gate_message(monkeypatch):
    monkeypatch.delenv("DAILY_PICK_PUBLISH_GATE", raising=False)
    _stub_score_path(monkeypatch, adjusted_confidence=0.25)
    pick = select_hourly_pick([_subnet()])
    assert pick["action"] == "HOLD"
    assert pick["hold_reason"]
    assert "below" in pick["hold_reason"].lower()
    assert pick["final_confidence"] == 0.25


def test_high_confidence_publishes_long(monkeypatch):
    monkeypatch.delenv("DAILY_PICK_PUBLISH_GATE", raising=False)
    _stub_score_path(monkeypatch, adjusted_confidence=0.55)
    pick = select_hourly_pick([_subnet()])
    assert pick["action"] == "long"
    assert pick.get("hold_reason") is None
    assert pick["final_confidence"] == 0.55


def test_highest_emission_pick_is_hold_fallback():
    out = _highest_emission_pick([_subnet(3, emission=9), _subnet(1, emission=1)])
    assert out["action"] == "HOLD"
    assert out["scenario_tags"]["fallback"] == "highest-emission"
    assert "Council scoring unavailable" in (out.get("hold_reason") or "")
    assert out["subnet"]["netuid"] == 3
    assert out.get("generated_at")


def test_hold_does_not_call_record_pick_prediction(monkeypatch):
    recorded = {"pick": False, "hold": False}

    def boom_pick(*_a, **_k):
        recorded["pick"] = True
        raise AssertionError("record_pick_prediction must not run on HOLD")

    def ok_hold(**kwargs):
        recorded["hold"] = True

    monkeypatch.setattr(
        "internal.learning.prediction_loop.record_pick_prediction", boom_pick
    )
    monkeypatch.setattr(
        "internal.learning.prediction_loop.record_hold_decision", ok_hold
    )

    pick = {
        "action": "HOLD",
        "hold_reason": "below gate",
        "subnet": {"netuid": 1, "name": "A"},
        "final_confidence": 0.2,
    }
    _record_pick_in_learning_loop(pick, [_subnet()], {}, "hour")
    assert recorded["hold"] is True
    assert recorded["pick"] is False

    recorded["hold"] = False
    _record_hour_pick(pick, [_subnet()], {})
    assert recorded["hold"] is True
    assert recorded["pick"] is False
