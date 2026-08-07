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

# A deliberately different calibration value returned by the live scorer.
# If pick-explain uses the live score instead of the persisted record the
# consistency test will catch the mismatch.
_LIVE_SCORE_CAL = {
    "factors": [{"name": "live_factor", "weight": 0.5, "raw": 0.9, "adjusted": 0.9}],
    "aggregate_score": 0.9,
    "method": "live-rescore",
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
# Uses _LIVE_SCORE_CAL (distinct from _SENTINEL_CAL) so the consistency test
# can verify pick-explain reads calibration from the persisted record and not
# from this live re-score.
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
    "telegram_evidence_calibration": _LIVE_SCORE_CAL,
}

# Fixture audit result used in pick-explain tests.
_FIXTURE_AUDIT = {"adjusted_confidence": 0.82, "concerns": []}

# Fixture subnet row — survives tradable_subnets filter (integer netuid > 0).
_FIXTURE_SUBNET = {"netuid": 42, "name": "MockNet", "symbol": "MOCK", "price": 1.0}

# Fixture get_or_create_today_pick result — SN42 is the published pick.
# Carries the sentinel calibration on the pick sub-object so the fix can
# return the persisted value instead of the live re-score (_LIVE_SCORE_CAL).
_FIXTURE_TODAY_PICK_STATE = {
    "date": _TODAY,
    "action": "long",
    "pick": {
        "subnet": {"netuid": 42, "name": "MockNet"},
        "telegram_evidence_calibration": _SENTINEL_CAL,
    },
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
    assert body.get("calibration_source") == "persisted", (
        f"Expected calibration_source 'persisted' when pick record carries calibration; "
        f"got {body.get('calibration_source')!r}"
    )


def test_calibration_field_consistent_across_endpoints():
    """Both /api/daily-pick (inside pick sub-object) and /api/pick-explain/{netuid}
    (top level) must carry telegram_evidence_calibration and agree on its value for
    the same published pick.

    The live scorer (_FIXTURE_SCORE) deliberately returns _LIVE_SCORE_CAL, which
    differs from _SENTINEL_CAL stored on the persisted pick record.  The fix
    requires pick-explain to read calibration from the persisted record for a
    published subnet so both endpoints agree on _SENTINEL_CAL.  If pick-explain
    falls back to the live scorer the final equality assertion catches the mismatch.
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
    # Confirm daily-pick returns the persisted sentinel, not the live score value.
    assert pick_obj["telegram_evidence_calibration"] == _SENTINEL_CAL, (
        f"daily-pick calibration should equal the persisted sentinel; "
        f"got {pick_obj['telegram_evidence_calibration']!r}"
    )

    with (
        patch("server._get_subnets_with_source", return_value=([_FIXTURE_SUBNET], "mock")),
        patch("server._market_context_with_weights", return_value={"weights": {}}),
        # Live scorer returns _LIVE_SCORE_CAL — pick-explain must NOT use this for
        # the published subnet; it must prefer the persisted _SENTINEL_CAL instead.
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

    explain_cal = explain["telegram_evidence_calibration"]
    # pick-explain must return the persisted sentinel, not the live rescore value.
    assert explain_cal != _LIVE_SCORE_CAL, (
        "pick-explain returned the live re-score calibration instead of the "
        f"persisted record value; got {explain_cal!r}"
    )
    assert explain_cal == _SENTINEL_CAL, (
        f"pick-explain calibration should equal the persisted sentinel; "
        f"got {explain_cal!r}"
    )
    assert explain.get("calibration_source") == "persisted", (
        f"Expected calibration_source 'persisted' when persisted pick carries calibration; "
        f"got {explain.get('calibration_source')!r}"
    )

    daily_cal = pick_obj["telegram_evidence_calibration"]
    # Both endpoints must now agree on the exact value.
    assert daily_cal == explain_cal, (
        f"Calibration value mismatch across endpoints: "
        f"daily-pick={daily_cal!r}, pick-explain={explain_cal!r}"
    )


# ---------------------------------------------------------------------------
# Fallback path: persisted pick record lacks telegram_evidence_calibration
# ---------------------------------------------------------------------------

# A today-pick state where the pick sub-object has NO calibration field —
# simulates an older persisted record written before the calibration feature.
_FIXTURE_TODAY_PICK_NO_CAL = {
    "date": _TODAY,
    "action": "long",
    "pick": {
        "subnet": {"netuid": 42, "name": "MockNet"},
        # telegram_evidence_calibration intentionally absent
    },
    "candidate": None,
    "reason": None,
}


def test_pick_explain_calibration_source_live_when_persisted_record_lacks_field():
    """When the persisted pick record predates the calibration feature (field absent),
    pick-explain must fall back to the live re-score value and annotate the response
    with calibration_source='live' so callers know the value was not stored at
    pick-creation time.
    """
    with (
        patch("server._get_subnets_with_source", return_value=([_FIXTURE_SUBNET], "mock")),
        patch("server._market_context_with_weights", return_value={"weights": {}}),
        patch("internal.council.pick_explain.score_subnet_for_day", return_value=_FIXTURE_SCORE),
        patch("internal.council.pick_explain.audit_daily_pick", return_value=_FIXTURE_AUDIT),
        patch(
            "internal.council.daily_pick_engine.get_or_create_today_pick",
            return_value=_FIXTURE_TODAY_PICK_NO_CAL,
        ),
    ):
        resp = client.get("/api/pick-explain/42")

    assert resp.status_code == 200
    body = resp.json()

    assert body.get("status") == "ok", (
        f"Expected status 'ok' from /api/pick-explain/42 with no-cal fixture; got: {body!r}"
    )
    assert "telegram_evidence_calibration" in body, (
        "telegram_evidence_calibration absent from /api/pick-explain ok response even in fallback path"
    )
    # Fallback must return the live re-score calibration, not None.
    assert body["telegram_evidence_calibration"] == _LIVE_SCORE_CAL, (
        f"Expected live re-score calibration (_LIVE_SCORE_CAL) in fallback path; "
        f"got {body['telegram_evidence_calibration']!r}"
    )
    assert body.get("calibration_source") == "live", (
        f"Expected calibration_source 'live' when persisted record lacks calibration field; "
        f"got {body.get('calibration_source')!r}"
    )


# ---------------------------------------------------------------------------
# HOLD/candidate subnet paths: gated_candidate and not_today_pick verdicts
# ---------------------------------------------------------------------------

# Today-pick state where SN42 is the gated candidate (no published pick yet).
# The pick sub-object belongs to a different subnet so published_n is None;
# candidate.subnet.netuid == 42 triggers the gated_candidate branch.
_FIXTURE_TODAY_PICK_GATED_CANDIDATE = {
    "date": _TODAY,
    "action": None,
    "pick": None,
    "candidate": {
        "subnet": {"netuid": 42, "name": "MockNet"},
        "telegram_evidence_calibration": _SENTINEL_CAL,
    },
    "reason": "Below publish-gate confidence threshold",
}

# Today-pick state where SN42 is neither the published pick nor the candidate —
# some other subnet (SN99) is the published pick.
_FIXTURE_TODAY_PICK_OTHER_PUBLISHED = {
    "date": _TODAY,
    "action": "long",
    "pick": {
        "subnet": {"netuid": 99, "name": "OtherNet"},
        "telegram_evidence_calibration": _SENTINEL_CAL,
    },
    "candidate": None,
    "reason": None,
}


def test_pick_explain_gated_candidate_calibration_from_live_score():
    """For a gated_candidate subnet pick-explain must return
    telegram_evidence_calibration sourced from the live re-score (calibration_source='live'),
    because the persisted-calibration optimisation only applies to the published pick.
    """
    with (
        patch("server._get_subnets_with_source", return_value=([_FIXTURE_SUBNET], "mock")),
        patch("server._market_context_with_weights", return_value={"weights": {}}),
        patch("internal.council.pick_explain.score_subnet_for_day", return_value=_FIXTURE_SCORE),
        patch("internal.council.pick_explain.audit_daily_pick", return_value=_FIXTURE_AUDIT),
        patch(
            "internal.council.daily_pick_engine.get_or_create_today_pick",
            return_value=_FIXTURE_TODAY_PICK_GATED_CANDIDATE,
        ),
    ):
        resp = client.get("/api/pick-explain/42")

    assert resp.status_code == 200
    body = resp.json()

    assert body.get("status") == "ok", (
        f"Expected status 'ok' for gated_candidate path; got: {body!r}"
    )
    assert body.get("verdict") == "gated_candidate", (
        f"Expected verdict 'gated_candidate'; got {body.get('verdict')!r}"
    )
    assert "telegram_evidence_calibration" in body, (
        "telegram_evidence_calibration absent from pick-explain response for gated_candidate"
    )
    # Calibration must come from the live scorer for non-published verdicts.
    assert body["telegram_evidence_calibration"] == _LIVE_SCORE_CAL, (
        f"Expected live re-score calibration (_LIVE_SCORE_CAL) for gated_candidate; "
        f"got {body['telegram_evidence_calibration']!r}"
    )
    assert body.get("calibration_source") == "live", (
        f"Expected calibration_source 'live' for gated_candidate; "
        f"got {body.get('calibration_source')!r}"
    )


def test_pick_explain_not_today_pick_calibration_from_live_score():
    """For a not_today_pick subnet pick-explain must return
    telegram_evidence_calibration sourced from the live re-score (calibration_source='live'),
    because the persisted-calibration optimisation only applies to the published pick.
    """
    with (
        patch("server._get_subnets_with_source", return_value=([_FIXTURE_SUBNET], "mock")),
        patch("server._market_context_with_weights", return_value={"weights": {}}),
        patch("internal.council.pick_explain.score_subnet_for_day", return_value=_FIXTURE_SCORE),
        patch("internal.council.pick_explain.audit_daily_pick", return_value=_FIXTURE_AUDIT),
        patch(
            "internal.council.daily_pick_engine.get_or_create_today_pick",
            return_value=_FIXTURE_TODAY_PICK_OTHER_PUBLISHED,
        ),
    ):
        resp = client.get("/api/pick-explain/42")

    assert resp.status_code == 200
    body = resp.json()

    assert body.get("status") == "ok", (
        f"Expected status 'ok' for not_today_pick path; got: {body!r}"
    )
    assert body.get("verdict") == "not_today_pick", (
        f"Expected verdict 'not_today_pick'; got {body.get('verdict')!r}"
    )
    assert "telegram_evidence_calibration" in body, (
        "telegram_evidence_calibration absent from pick-explain response for not_today_pick"
    )
    # Calibration must come from the live scorer for non-published verdicts.
    assert body["telegram_evidence_calibration"] == _LIVE_SCORE_CAL, (
        f"Expected live re-score calibration (_LIVE_SCORE_CAL) for not_today_pick; "
        f"got {body['telegram_evidence_calibration']!r}"
    )
    assert body.get("calibration_source") == "live", (
        f"Expected calibration_source 'live' for not_today_pick; "
        f"got {body.get('calibration_source')!r}"
    )
