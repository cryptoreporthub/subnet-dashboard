"""§32 — pick explain API."""

from datetime import datetime, timezone
from unittest.mock import patch

from fastapi.testclient import TestClient

from server import app

client = TestClient(app)

# ---------------------------------------------------------------------------
# Shared fixture data
# ---------------------------------------------------------------------------

_SENTINEL_CAL = {
    "factors": [{"name": "mock_factor", "weight": 1.0, "raw": 0.6, "adjusted": 0.6}],
    "aggregate_score": 0.6,
    "method": "unit-test",
}

_TODAY = datetime.now(timezone.utc).date().isoformat()

# Persisted pick record (as returned by _find_today from the JSON store).
# judge_scores_at_creation is pre-populated so attach_judge_scores_to_daily_pick
# skips the live conviction_bands IO path.
_FIXTURE_PICK_RECORD = {
    "date": _TODAY,
    "status": "ok",
    "action": "long",
    "pick": {
        "subnet": {"netuid": 42, "name": "MockNet", "symbol": "MOCK"},
        "score": 88.5,
        "confidence": 0.82,
        "final_confidence": 0.82,
        "expert_contributions": {},
        "scenario_tags": [],
        "audit": {"adjusted_confidence": 0.82, "concerns": []},
        "action": "long",
        "tie_break": None,
        "prediction": {},
        "reasons": [],
        "impact": None,
        "signal_impact": {},
        "signal_contributions": {},
        "active_signals": [],
        "judge_scores_at_creation": [{"judge": "mock", "score": 0.8}],
        "telegram_evidence_calibration": _SENTINEL_CAL,
    },
    "candidate": None,
    "reason": None,
    "regime": "bull",
    "rotation_summary": {},
    "market_context": {},
}

# Fixture score result from score_subnet_for_day used in pick-explain tests.
_FIXTURE_SCORE = {
    "total_score": 88.5,
    "confidence": 0.82,
    "expert_contributions": {},
    "scenario_tags": [],
    "horizon": "day",
    "horizon_type": "day",
    "weights_used": {},
    "signal_impact": {},
    "signal_contributions": {},
    "active_signals": [],
    "pump_overlay": None,
    "telegram_evidence_calibration": _SENTINEL_CAL,
}

# Fixture audit result used in pick-explain tests.
_FIXTURE_AUDIT = {"adjusted_confidence": 0.82, "concerns": []}

# Fixture subnet row — survives tradable_subnets filter (integer netuid > 0).
_FIXTURE_SUBNET = {"netuid": 42, "name": "MockNet", "symbol": "MOCK", "price": 1.0}

# Fixture get_or_create_today_pick result — SN42 is the published pick.
_FIXTURE_TODAY_PICK_STATE = {
    "date": _TODAY,
    "action": "long",
    "pick": {"subnet": {"netuid": 42, "name": "MockNet"}},
    "candidate": None,
    "reason": None,
}


# ---------------------------------------------------------------------------
# Original tests (preserved)
# ---------------------------------------------------------------------------


def test_pick_explain_returns_ok():
    resp = client.get("/api/pick-explain/1")
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("status") in ("ok", "not_found")
    if body.get("status") == "ok":
        assert body.get("verdict") in (
            "published",
            "gated_candidate",
            "not_today_pick",
        )
        assert "blockers" in body


def test_explain_subnet_not_found():
    from internal.council.pick_explain import explain_subnet

    out = explain_subnet(99999, [])
    assert out["status"] == "not_found"


def test_explain_blockers_dedupe_audit_gate():
    from internal.council.pick_explain import _unique_blockers

    blockers = _unique_blockers(
        [
            "Confidence 29% below 45% audit gate — no long call published",
            "Confidence 29% below 45% audit gate",
            "Thin volume: $1,573 < $5k",
        ]
    )
    assert len(blockers) == 2
    assert any("Thin volume" in b for b in blockers)


# ---------------------------------------------------------------------------
# Contract: telegram_evidence_calibration survives enrichment and reaches clients
# ---------------------------------------------------------------------------


def test_daily_pick_calibration_survives_enrichment():
    """telegram_evidence_calibration placed on the pick sub-object by pick_daily_winner
    must survive _enrich_daily_pick_payload_lite unchanged and appear in the
    /api/daily-pick response body.

    Seeds a fixture persisted pick with a sentinel calibration value, runs the
    full enrichment path, and asserts the sentinel is still present and unmodified.
    """
    with (
        patch("internal.council.daily_pick_engine._load", return_value=[_FIXTURE_PICK_RECORD]),
        patch("internal.council.daily_pick_engine._find_today", return_value=_FIXTURE_PICK_RECORD),
    ):
        resp = client.get("/api/daily-pick")

    assert resp.status_code == 200
    body = resp.json()

    pick_obj = body.get("pick")
    assert isinstance(pick_obj, dict), (
        f"Expected pick sub-object in /api/daily-pick response; got: {pick_obj!r}"
    )
    assert "telegram_evidence_calibration" in pick_obj, (
        "telegram_evidence_calibration was dropped during enrichment of /api/daily-pick pick sub-object"
    )
    assert pick_obj["telegram_evidence_calibration"] == _SENTINEL_CAL, (
        f"telegram_evidence_calibration was mutated during enrichment; "
        f"expected {_SENTINEL_CAL!r}, got {pick_obj['telegram_evidence_calibration']!r}"
    )


def test_pick_explain_calibration_field_contract():
    """telegram_evidence_calibration must appear at the top level of a successful
    /api/pick-explain response for a tradable subnet.

    Uses mocked subnets, score, audit, and today-pick state to guarantee
    status == 'ok' and deterministic calibration output without live IO.
    """
    with (
        patch("server._get_subnets_with_source", return_value=([_FIXTURE_SUBNET], "mock")),
        patch("server._market_context_with_weights", return_value={"weights": {}}),
        patch("internal.council.pick_explain.score_subnet_for_day", return_value=_FIXTURE_SCORE),
        patch("internal.council.pick_explain.audit_daily_pick", return_value=_FIXTURE_AUDIT),
        patch(
            "internal.council.daily_pick_engine.get_or_create_today_pick",
            return_value=_FIXTURE_TODAY_PICK_STATE,
        ),
    ):
        resp = client.get("/api/pick-explain/42")

    assert resp.status_code == 200
    body = resp.json()

    assert body.get("status") == "ok", (
        f"Expected status 'ok' from /api/pick-explain/42 with mocked data; got: {body!r}"
    )
    assert "telegram_evidence_calibration" in body, (
        "telegram_evidence_calibration absent from /api/pick-explain ok response"
    )
    assert body["telegram_evidence_calibration"] == _SENTINEL_CAL, (
        f"telegram_evidence_calibration value mismatch in /api/pick-explain; "
        f"expected {_SENTINEL_CAL!r}, got {body['telegram_evidence_calibration']!r}"
    )


def test_calibration_field_consistent_across_endpoints():
    """Both /api/daily-pick (inside pick sub-object) and /api/pick-explain/{netuid}
    (top level) must carry telegram_evidence_calibration and agree on its value for
    the same published pick.

    Uses shared fixture data so both endpoints operate on identical calibration
    inputs, confirming neither the enrichment pipeline nor the explain scorer
    silently drops or nullifies the field.
    """
    with (
        patch("internal.council.daily_pick_engine._load", return_value=[_FIXTURE_PICK_RECORD]),
        patch("internal.council.daily_pick_engine._find_today", return_value=_FIXTURE_PICK_RECORD),
    ):
        daily_resp = client.get("/api/daily-pick")

    assert daily_resp.status_code == 200
    daily = daily_resp.json()
    pick_obj = daily.get("pick")
    assert isinstance(pick_obj, dict), (
        "Expected a published pick dict in /api/daily-pick when seeded with fixture"
    )
    assert "telegram_evidence_calibration" in pick_obj, (
        "telegram_evidence_calibration absent from /api/daily-pick pick sub-object"
    )

    with (
        patch("server._get_subnets_with_source", return_value=([_FIXTURE_SUBNET], "mock")),
        patch("server._market_context_with_weights", return_value={"weights": {}}),
        patch("internal.council.pick_explain.score_subnet_for_day", return_value=_FIXTURE_SCORE),
        patch("internal.council.pick_explain.audit_daily_pick", return_value=_FIXTURE_AUDIT),
        patch(
            "internal.council.daily_pick_engine.get_or_create_today_pick",
            return_value=_FIXTURE_TODAY_PICK_STATE,
        ),
    ):
        explain_resp = client.get("/api/pick-explain/42")

    assert explain_resp.status_code == 200
    explain = explain_resp.json()
    assert explain.get("status") == "ok", (
        f"Expected status 'ok' from /api/pick-explain/42 with mocked data; got: {explain!r}"
    )
    assert "telegram_evidence_calibration" in explain, (
        "telegram_evidence_calibration absent from /api/pick-explain ok response"
    )

    daily_cal = pick_obj["telegram_evidence_calibration"]
    explain_cal = explain["telegram_evidence_calibration"]
    # Both endpoints used the same sentinel fixture — values must match exactly.
    assert daily_cal == explain_cal, (
        f"Calibration value mismatch across endpoints: "
        f"daily-pick={daily_cal!r}, pick-explain={explain_cal!r}"
    )
