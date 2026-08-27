"""Drift / QA observer — eight checks, Policy §4, observation-only."""

from __future__ import annotations

import inspect
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from internal.bots.drift_qa import (
    CHECKS,
    CHECK_DEGRADED_HTTP_200S,
    CHECK_DISAGREEMENT,
    CHECK_HYDRATION_FAILS,
    CHECK_MISSING_FIELDS,
    CHECK_READINESS_DROPS,
    CHECK_SHAPE_CHANGES,
    CHECK_STALE_DATA,
    CHECK_STUCK_PANELS,
    EVIDENCE_CONTRADICTORY,
    EVIDENCE_SUPPORTING,
    EVIDENCE_UNAVAILABLE,
    MUTATIONS_ALLOWED,
    OBSERVATION_ONLY,
    RETRIES_ALLOWED,
    DisagreementPair,
    DriftSnapshot,
    ObservedPayload,
    classify_evidence,
    observe,
)
from internal.ops.notify import notify as notify_fn


NOW = datetime(2026, 8, 27, tzinfo=timezone.utc)


def _by_name(report):
    return {item.name: item for item in report.checks}


def test_eight_named_checks_always_present():
    report = observe(DriftSnapshot())
    assert tuple(item.name for item in report.checks) == CHECKS
    assert len(CHECKS) == 8


def test_healthy_snapshot_is_ok():
    captured = (NOW - timedelta(seconds=30)).isoformat()
    snapshot = DriftSnapshot(
        payloads=(
            ObservedPayload(
                name="/api/summary",
                source="internal/server.py#get_summary",
                freshness_source="live_feed",
                http_status=200,
                body={"status": "success", "summary": {"total_subnets": 120}},
                expected_keys=("status", "summary"),
                expected_types=(("status", "str"),),
                captured_at=captured,
                labeled_live=True,
                hydration_ok=True,
                ssr_keys=("hero", "daily-pick"),
                client_keys=("hero", "daily-pick"),
                loading=False,
                loading_seconds=0.2,
            ),
            ObservedPayload(
                name="/api/stats",
                source="internal/server.py#get_stats",
                freshness_source="live_feed",
                http_status=200,
                body={"status": "success", "summary": {"total_subnets": 120}},
                expected_keys=("status", "summary"),
                captured_at=captured,
            ),
            ObservedPayload(
                name="/api/ops/readiness",
                source="internal/ops/readiness.py",
                freshness_source="learning_health",
                http_status=200,
                body={
                    "status": "ready",
                    "ready": True,
                    "issues": [],
                    "checked_at": captured,
                },
                captured_at=captured,
                prior_body={"status": "ready", "ready": True},
            ),
        ),
        pairs=(
            DisagreementPair(
                "/api/summary",
                "/api/stats",
                ("summary.total_subnets",),
            ),
        ),
        now=NOW,
    )
    report = observe(snapshot)
    assert report.status == "ok"
    assert report.bot == "drift_qa"
    assert report.recommended_action is None
    assert report.approval_required is False
    assert report.audit["observation_only"] is True
    assert report.audit["retries"] == 0
    assert report.audit["mutations"] == 0
    by_name = _by_name(report)
    for name in CHECKS:
        assert by_name[name].flagged is False, (name, by_name[name].details)


def test_missing_fields_and_shape_changes():
    snapshot = DriftSnapshot(
        payloads=(
            ObservedPayload(
                name="/api/summary",
                source="fixture",
                http_status=200,
                body={"status": 1, "extra": True},
                expected_keys=("status", "summary"),
                expected_types=(("status", "str"),),
            ),
        ),
        now=NOW,
    )
    report = observe(snapshot)
    by_name = _by_name(report)
    assert by_name[CHECK_MISSING_FIELDS].flagged is True
    assert by_name[CHECK_SHAPE_CHANGES].flagged is True
    assert by_name[CHECK_MISSING_FIELDS].evidence_class == EVIDENCE_CONTRADICTORY
    assert any(item.tag == "shape_vs_schema" for item in report.contradictions)


def test_hydration_fail_is_flagged_without_retry():
    calls = {"retry": 0, "mutate": 0}

    def retry_hydration():
        calls["retry"] += 1
        raise AssertionError("Drift QA must not retry hydration")

    def mutate_state():
        calls["mutate"] += 1
        raise AssertionError("Drift QA must not mutate state")

    snapshot = DriftSnapshot(
        payloads=(
            ObservedPayload(
                name="/",
                source="ssr",
                hydration_ok=False,
                ssr_keys=("hero",),
                client_keys=("hero", "daily-pick"),
            ),
        ),
        now=NOW,
    )
    report = observe(snapshot)
    assert _by_name(report)[CHECK_HYDRATION_FAILS].flagged is True
    assert any(item.tag == "ssr_vs_client" for item in report.contradictions)
    assert calls == {"retry": 0, "mutate": 0}
    assert "retry_hydration" not in inspect.signature(observe).parameters
    retry_hydration
    mutate_state


def test_observation_only_contract():
    assert OBSERVATION_ONLY is True
    assert MUTATIONS_ALLOWED is False
    assert RETRIES_ALLOWED is False
    source = inspect.getsource(observe)
    assert "for _ in range" not in source
    assert "while " not in source
    assert "open(" not in source
    assert ".write(" not in source
    assert "retry_hydration" not in source
    assert inspect.signature(observe).parameters.keys() == {"snapshot"}


def test_stuck_panel_and_stale_live_label():
    snapshot = DriftSnapshot(
        payloads=(
            ObservedPayload(
                name="section-hero",
                source="ui",
                panel="section-hero",
                loading=True,
                loading_seconds=12.0,
                loading_timeout_seconds=10.0,
            ),
            ObservedPayload(
                name="/api/subnets",
                source="internal/subnets",
                freshness_source="live_feed",
                captured_at=(NOW - timedelta(hours=3)).isoformat(),
                labeled_live=True,
                http_status=200,
                body={"status": "success"},
            ),
        ),
        now=NOW,
    )
    report = observe(snapshot)
    by_name = _by_name(report)
    assert by_name[CHECK_STUCK_PANELS].flagged is True
    assert by_name[CHECK_STALE_DATA].flagged is True
    assert by_name[CHECK_STALE_DATA].severity == "critical"
    assert any(item.tag == "live_label_vs_freshness" for item in report.contradictions)
    assert report.freshness["status"] in {"stale", "degraded", "missing"}
    assert report.freshness.get("sources") or report.freshness.get("source")


def test_disagreement_and_readiness_drop():
    snapshot = DriftSnapshot(
        payloads=(
            ObservedPayload(
                name="/api/summary",
                source="summary",
                http_status=200,
                body={"summary": {"total_subnets": 120}},
            ),
            ObservedPayload(
                name="/api/stats",
                source="stats",
                http_status=200,
                body={"summary": {"total_subnets": 8}},
            ),
            ObservedPayload(
                name="/api/ops/readiness",
                source="internal/ops/readiness.py",
                http_status=200,
                body={"status": "degraded", "ready": False, "checked_at": NOW.isoformat()},
                prior_body={"status": "ready", "ready": True, "issues": [], "checked_at": NOW.isoformat()},
            ),
        ),
        pairs=(DisagreementPair("/api/summary", "/api/stats", ("summary.total_subnets",)),),
        now=NOW,
    )
    report = observe(snapshot)
    by_name = _by_name(report)
    assert by_name[CHECK_DISAGREEMENT].flagged is True
    assert by_name[CHECK_READINESS_DROPS].flagged is True
    assert "issues" in " ".join(by_name[CHECK_READINESS_DROPS].details)
    assert any(item.tag == "sources_disagree" for item in report.contradictions)
    assert any(item.tag == "readiness_vs_prior" for item in report.contradictions)


def test_degraded_http_200_from_observability_shape():
    snapshot = DriftSnapshot(
        payloads=(
            ObservedPayload(
                name="/api/council/weights",
                source="internal/judges",
                http_status=200,
                body={
                    "status": "degraded",
                    "data": None,
                    "weights_degraded": True,
                    "error": "worker unreachable",
                },
            ),
        ),
        now=NOW,
    )
    report = observe(snapshot)
    check = _by_name(report)[CHECK_DEGRADED_HTTP_200S]
    assert check.flagged is True
    assert check.evidence_class == EVIDENCE_CONTRADICTORY
    assert any("status=degraded" in item for item in check.details)
    assert any("data=null" in item for item in check.details)
    assert any("weights_degraded=true" in item for item in check.details)
    assert any(item.tag == "http_ok_vs_degraded_body" for item in report.contradictions)
    assert report.recommended_action is None


def test_policy_section_4_classes():
    assert classify_evidence(flagged=False) == EVIDENCE_SUPPORTING
    assert classify_evidence(flagged=True) == EVIDENCE_CONTRADICTORY
    assert classify_evidence(flagged=False, unavailable=True) == EVIDENCE_UNAVAILABLE
    snapshot = DriftSnapshot()
    report = observe(snapshot)
    unavailable = {
        item.name: item.evidence_class
        for item in report.checks
        if item.evidence_class == EVIDENCE_UNAVAILABLE
    }
    assert CHECK_HYDRATION_FAILS in unavailable
    assert any("WARNING: source unavailable" in " ".join(item.details) for item in report.checks)


def test_notify_is_the_only_side_effect():
    with patch("internal.ops.notify.notify") as mocked:
        report = observe(
            DriftSnapshot(
                payloads=(
                    ObservedPayload(
                        name="/api/x",
                        source="fixture",
                        http_status=200,
                        body={"status": "degraded", "data": None, "_degraded": True},
                    ),
                )
            )
        )
    mocked.assert_called_once()
    args, kwargs = mocked.call_args
    event = args[0] if args else kwargs.get("event")
    assert event == "bot_observe"
    assert kwargs["bot"] == "drift_qa"
    assert kwargs["observation_only"] is True
    assert report.status == "degraded"


def test_notify_module_does_not_write_state(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    notify_fn("bot_observe", bot="drift_qa", observation_only=True)
    assert list(tmp_path.iterdir()) == []


def test_empty_snapshot_is_not_ok():
    report = observe(DriftSnapshot())
    assert report.status == "degraded"
    assert report.summary == "No observations supplied"
    assert report.recommended_action is None
    assert all(item.evidence_class == EVIDENCE_UNAVAILABLE for item in report.checks)


def test_data_null_alone_on_http_200_is_degraded():
    report = observe(
        DriftSnapshot(
            payloads=(
                ObservedPayload(
                    name="/api/council/weights",
                    source="fixture",
                    http_status=200,
                    body={"data": None, "error": "worker unreachable"},
                ),
            )
        )
    )
    check = _by_name(report)[CHECK_DEGRADED_HTTP_200S]
    assert check.flagged is True
    assert any("data=null" in item for item in check.details)


def test_unknown_panel_age_is_unavailable_not_stuck():
    report = observe(
        DriftSnapshot(
            payloads=(
                ObservedPayload(
                    name="section-hero",
                    source="ui",
                    panel="section-hero",
                    loading=True,
                    loading_seconds=None,
                ),
            )
        )
    )
    check = _by_name(report)[CHECK_STUCK_PANELS]
    assert check.flagged is False
    assert check.evidence_class == EVIDENCE_UNAVAILABLE


def test_null_body_with_timestamp_is_degraded_freshness():
    captured = (NOW - timedelta(seconds=10)).isoformat()
    report = observe(
        DriftSnapshot(
            payloads=(
                ObservedPayload(
                    name="/api/x",
                    source="fixture",
                    freshness_source="learning_health",
                    http_status=200,
                    body=None,
                    captured_at=captured,
                    labeled_live=True,
                ),
            ),
            now=NOW,
        )
    )
    assert report.freshness["status"] == "degraded"
    assert _by_name(report)[CHECK_DEGRADED_HTTP_200S].flagged is True


def test_degraded_body_is_not_classified_fresh():
    captured = (NOW - timedelta(seconds=30)).isoformat()
    report = observe(
        DriftSnapshot(
            payloads=(
                ObservedPayload(
                    name="/api/council/weights",
                    source="fixture",
                    freshness_source="learning_health",
                    http_status=200,
                    body={"status": "degraded", "data": None, "_degraded": True},
                    captured_at=captured,
                    labeled_live=True,
                ),
            ),
            now=NOW,
        )
    )
    assert report.freshness["status"] == "degraded"
    assert _by_name(report)[CHECK_STALE_DATA].flagged is True


def test_import_is_safe():
    import internal.bots.drift_qa as module

    assert module.OBSERVATION_ONLY is True
    assert module.BOT_NAME == "drift_qa"
    src = inspect.getsource(module)
    assert "build_evidence_report" not in src
    assert "import urllib" not in src
    assert "import requests" not in src
