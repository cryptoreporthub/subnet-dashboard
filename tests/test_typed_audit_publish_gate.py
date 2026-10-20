"""Audit verdicts are typed, a blocked candidate stays blocked, and the publish gate obeys it."""

import pytest

from internal.council.publish_gate import audit_publish_guard
from internal.council.red_team import (
    MISSING_CRITICAL_FIELD,
    NOT_TRADABLE,
    audit_daily_pick,
    has_concern,
)

HEALTHY = {"netuid": 7, "name": "Sn7", "price": 1.0, "volume": 9000.0, "confidence": 0.7}


def test_healthy_candidate_is_approved_with_no_blocking_codes():
    audit = audit_daily_pick(dict(HEALTHY), [dict(HEALTHY)])
    assert audit["approved"] is True and audit["blocked"] is False
    assert not has_concern(audit, NOT_TRADABLE) and not has_concern(audit, MISSING_CRITICAL_FIELD)


def test_blocked_candidate_is_not_resurrected_by_later_haircut_flags():
    """Regression for F11: the 0.88 floor used to lift a 0.0 multiplier when any later flag fired."""
    root = {**HEALTHY, "netuid": 0, "volume": 10.0, "price_change_24h": 35.0, "is_overvalued": True}
    audit = audit_daily_pick(root, [root])
    assert has_concern(audit, NOT_TRADABLE)
    assert audit["approved"] is False and audit["blocked"] is True
    assert audit["confidence_multiplier"] == 0.0
    assert audit["adjusted_confidence"] == 0.0


def test_missing_critical_field_blocks_and_stays_zero():
    sn = {**HEALTHY, "price": None, "volume": 10.0}
    audit = audit_daily_pick(sn, [sn])
    assert has_concern(audit, MISSING_CRITICAL_FIELD)
    assert audit["approved"] is False and audit["adjusted_confidence"] == 0.0


def test_advisory_concerns_do_not_block():
    sn = {**HEALTHY, "volume": 50.0, "price_change_24h": 25.0}
    audit = audit_daily_pick(sn, [sn])
    assert audit["approved"] is True
    assert 0.0 < audit["confidence_multiplier"] < 1.0
    assert audit["concerns"]


def test_legacy_audit_without_codes_still_classifies():
    legacy = {"approved": False, "concerns": ["Missing critical field: price"]}
    assert has_concern(legacy, MISSING_CRITICAL_FIELD)
    assert not has_concern(legacy, NOT_TRADABLE)


def test_publish_gate_blocks_unapproved_and_unaudited_picks():
    assert audit_publish_guard({"approved": True})["approved"] is True
    rejected = audit_publish_guard({
        "approved": False,
        "concerns": ["Thin volume: $400", "Missing critical field: price"],
        "concern_codes": ["advisory", MISSING_CRITICAL_FIELD],
    })
    assert rejected["approved"] is False
    assert "Missing critical field: price" in rejected["reason"]
    assert audit_publish_guard(None)["approved"] is False
    assert audit_publish_guard({})["approved"] is False


def test_engine_holds_an_audit_rejected_pick_even_above_the_confidence_gate(monkeypatch):
    """The gate used to ignore audit['approved']; a rejected candidate with high confidence published."""
    from internal.council import hourly_pick
    from internal.council.hourly_pick import clear_hourly_pick_cache, select_hourly_pick

    clear_hourly_pick_cache()
    monkeypatch.delenv("DAILY_PICK_PUBLISH_GATE", raising=False)
    monkeypatch.setattr(hourly_pick, "score_subnet_for_hour", lambda sn, ctx: {
        "total_score": 80.0, "confidence": 0.9, "expert_contributions": {}, "scenario_tags": {},
    })
    monkeypatch.setattr(hourly_pick, "audit_daily_pick", lambda c, s: {
        "approved": False, "concerns": ["Missing critical field: price"],
        "concern_codes": [MISSING_CRITICAL_FIELD], "adjusted_confidence": 0.9,
    })
    monkeypatch.setattr(hourly_pick, "attach_council_prediction", lambda *a, **k: {"statement": "t"})
    monkeypatch.setattr(hourly_pick, "unpack_score_learning_fields", lambda score: {
        "signal_impact": None, "signal_contributions": None, "active_signals": [],
    })
    monkeypatch.setattr(hourly_pick, "pick_reasons", lambda *a: [])
    pick = select_hourly_pick([{"netuid": 1, "name": "SN1", "price": 1.0, "volume": 5000, "emission": 2.0}])
    assert pick["action"] == "HOLD"
    assert "Audit blocked" in pick["hold_reason"]
    clear_hourly_pick_cache()
