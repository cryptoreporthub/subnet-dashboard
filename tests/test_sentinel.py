"""Sentinel bot: predicate evaluation, immutable reports, read-only observe."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, fields, is_dataclass
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from internal.bots.sentinel import (
    BOT_NAME,
    FINDING_STATUSES,
    PREDICATE_NAMES,
    STATUS_HEALTHY,
    STATUS_UNHEALTHY,
    STATUS_UNKNOWN,
    HealthReport,
    collect_snapshot,
    evaluate_predicates,
    observe,
)
from internal.ops.bot_policy import classify_freshness


NOW = datetime(2026, 8, 27, tzinfo=timezone.utc)
CHECKED = "2026-08-27T00:00:00Z"
_FRESHNESS_FIELDS = ("age", "confidence", "last_updated", "source")


def _healthy_snapshot() -> dict:
    return {
        "checked_at": CHECKED,
        "latency_ms": 12.0,
        "liveness": {
            "status": "ok",
            "live": True,
            "checked_at": CHECKED,
            "volume": {"path": "data", "writable": True},
            "worker_peer": {
                "expected": True,
                "alive": True,
                "peer": "inline_worker",
                "source": "file",
                "heartbeat": {"ts": CHECKED},
            },
        },
        "worker_peer": {
            "expected": True,
            "alive": True,
            "peer": "inline_worker",
            "source": "file",
            "heartbeat": {"ts": CHECKED},
        },
        "resolver": {
            "running": True,
            "last_run_at": CHECKED,
            "last_run_ok": True,
            "consecutive_failures": 0,
            "lifecycle": "running",
        },
        "loop_health": {
            "status": "ok",
            "checked_at": CHECKED,
            "pending": 0,
            "last_resolver_tick": CHECKED,
            "resolver": {
                "running": True,
                "lifecycle": "running",
                "warming": False,
                "last_ok": True,
            },
            "watchdog": {"warning": False, "pending_count": 0},
            "pick_scheduler": {
                "daily": {"running": True, "last_run_ok": True, "last_run_at": CHECKED},
                "hour": {"running": True, "last_run_ok": True},
            },
            "snapshot_age_seconds": 30,
            "ledger": {"gap": False},
        },
        "watchdog": {"warning": False, "pending_count": 0},
        "feed": {
            "effective_source": "blockmachine",
            "likely_total": 128,
            "live_cache": {"synced_at": CHECKED, "count": 128, "stale": False},
        },
        "live": {
            "stale": False,
            "last_sync": CHECKED,
            "age_seconds": 20,
            "subnet_count": 128,
        },
        "sync": {"last_sync_at": CHECKED, "last_sync_ok": True, "background_running": True},
        "file_freshness": {
            "overall": {"any_stale": False, "checked_at": CHECKED},
            "price_cache": {"last_updated": CHECKED, "is_stale": False},
        },
        "job_scheduler": {"running": True, "job_count": 3, "last_failures": {}},
        "pump_scheduler": {"running": True, "last_run_ok": True, "last_run_at": CHECKED},
        "evidence": {
            "status": "ok",
            "alerts": [],
            "evidence_sources": [
                classify_freshness("learning_outcomes", CHECKED, now=NOW),
            ],
            "learning_outcomes": {"council_health": {"escalation": "OK"}},
        },
        "snapshot_guard": {"installed": True, "cold": False},
    }


def _by_name(predicates):
    return {item.name: item for item in predicates}


def _assert_freshness_aliases(envelope):
    for key in _FRESHNESS_FIELDS:
        assert key in envelope, key
    assert envelope["age"] == envelope.get("age_seconds")
    assert envelope["last_updated"] == (envelope.get("captured_at") or envelope.get("observed_at"))
    if envelope.get("status") in {"fresh", "aging", "stale"}:
        assert envelope["confidence"] in (1.0, 0.5, 0.25)
    else:
        assert envelope["confidence"] is None


def test_sentinel_module_is_importable():
    import internal.bots.sentinel as sentinel

    assert sentinel.BOT_NAME == "sentinel"
    assert sentinel.PREDICATE_NAMES == PREDICATE_NAMES
    assert len(PREDICATE_NAMES) == 10
    assert FINDING_STATUSES == (STATUS_HEALTHY, STATUS_UNHEALTHY, STATUS_UNKNOWN)


def test_health_report_is_frozen():
    report = observe(snapshot=_healthy_snapshot())
    assert isinstance(report, HealthReport)
    assert is_dataclass(HealthReport)
    assert HealthReport.__dataclass_params__.frozen is True
    assert not any(name.startswith("set_") for name in dir(report) if not name.startswith("_"))
    with pytest.raises(FrozenInstanceError):
        report.status = "mutated"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        report.summary = "nope"  # type: ignore[misc]
    with pytest.raises(TypeError):
        report.freshness["status"] = "forged"
    with pytest.raises(TypeError):
        report.evidence["status"] = "forged"
    with pytest.raises(TypeError):
        report.predicates[0].freshness["status"] = "forged"
    with pytest.raises(TypeError):
        report.predicates[0].metrics["invented"] = True
    field_names = {item.name for item in fields(HealthReport)}
    assert "status" in field_names
    assert "freshness" in field_names


def test_report_includes_policy_2_2_freshness_fields():
    report = observe(snapshot=_healthy_snapshot())
    freshness = report.freshness
    assert freshness["status"] in {"fresh", "aging", "stale", "missing", "degraded"}
    assert "observed_at" in freshness
    assert "age_seconds" in freshness
    assert "sources" in freshness
    assert freshness["sources"]
    _assert_freshness_aliases(freshness)
    for envelope in freshness["sources"]:
        assert envelope["source"]
        assert envelope["status"] in {"fresh", "aging", "stale", "missing", "degraded"}
        assert "captured_at" in envelope
        assert "age_seconds" in envelope
        assert "authoritative" in envelope
        assert "thresholds_seconds" in envelope
        _assert_freshness_aliases(envelope)
    for item in report.predicates:
        _assert_freshness_aliases(item.freshness)
        assert item.status in FINDING_STATUSES


def test_ten_predicates_evaluate_healthy_snapshot():
    results = _by_name(evaluate_predicates(_healthy_snapshot(), now=NOW))
    assert tuple(results) == PREDICATE_NAMES
    for name in PREDICATE_NAMES:
        if name == "deployment":
            assert results[name].status == STATUS_UNKNOWN, name
            assert results[name].reason
        else:
            assert results[name].status == STATUS_HEALTHY, name
            assert results[name].metrics
        assert results[name].status in FINDING_STATUSES
    report = observe(snapshot=_healthy_snapshot())
    assert report.status == STATUS_UNKNOWN
    assert report.unknowns == ("deployment",)
    assert report.bot == BOT_NAME
    assert report.approval_required is False
    assert report.approval["status"] == "not_required"
    assert report.recommended_action is None
    assert report.confidence is None


def test_missing_signals_are_unknown_not_fabricated():
    results = _by_name(evaluate_predicates({}, now=NOW))
    assert tuple(results) == PREDICATE_NAMES
    for name, item in results.items():
        assert item.status == STATUS_UNKNOWN, name
        assert item.reason, name
        assert isinstance(item.reason, str)
        assert item.freshness["status"] in {"missing", "degraded"}
        assert item.metrics is not None
    report = observe(snapshot={})
    assert report.status == STATUS_UNKNOWN
    assert set(report.unknowns) == set(PREDICATE_NAMES)


def test_unknown_findings_include_reason():
    snap = _healthy_snapshot()
    snap.pop("latency_ms")
    snap["worker_peer"] = {"expected": True, "alive": None, "source": "deferred"}
    results = _by_name(evaluate_predicates(snap, now=NOW))
    latency = results["latency"]
    assert latency.status == STATUS_UNKNOWN
    assert latency.reason == "no in-process health-path timing"
    worker = results["worker"]
    assert worker.status == STATUS_UNKNOWN
    assert "deferred" in worker.reason
    deployment = results["deployment"]
    assert deployment.status == STATUS_UNKNOWN
    assert "GitHub" in deployment.reason or "CI" in deployment.reason


def test_failing_predicates_use_real_snapshot_fields():
    snap = _healthy_snapshot()
    snap["liveness"]["live"] = False
    snap["liveness"]["status"] = "down"
    snap["latency_ms"] = 9000.0
    snap["worker_peer"]["alive"] = False
    snap["resolver"]["consecutive_failures"] = 3
    snap["resolver"]["last_run_ok"] = False
    snap["loop_health"]["resolver"]["running"] = False
    snap["watchdog"]["warning"] = True
    snap["watchdog"]["reason"] = "pending_past_grace"
    snap["feed"]["effective_source"] = "none"
    snap["file_freshness"]["overall"]["any_stale"] = True
    snap["job_scheduler"]["last_failures"] = {"freshness-background-sync": 2}
    snap["loop_health"]["status"] = "stalled"
    snap["snapshot_guard"]["cold"] = True

    results = _by_name(evaluate_predicates(snap, now=NOW))
    for name in PREDICATE_NAMES:
        assert results[name].status == STATUS_UNHEALTHY, name
        assert results[name].metrics
        assert results[name].status in FINDING_STATUSES
    report = observe(snapshot=snap)
    assert report.status == STATUS_UNHEALTHY


def test_degraded_volume_is_unhealthy_not_unknown():
    snap = _healthy_snapshot()
    snap["liveness"]["status"] = "degraded"
    snap["liveness"]["volume"]["writable"] = False
    result = _by_name(evaluate_predicates(snap, now=NOW))["api_health"]
    assert result.status == STATUS_UNHEALTHY
    assert "writable" in result.detail
    assert result.metrics["volume"]["writable"] is False


def test_observe_uses_evidence_and_notify(monkeypatch):
    calls = []
    evidence_calls = []

    def fake_notify(event, message="", **kwargs):
        calls.append((event, message, kwargs))

    def fake_status(message, *, level="info", **kwargs):
        calls.append(("status", message, {"level": level, **kwargs}))

    def fake_evidence():
        evidence_calls.append(True)
        return {"status": "ok", "alerts": [], "evidence_sources": []}

    monkeypatch.setattr("internal.bots.sentinel.log_event", fake_notify)
    monkeypatch.setattr("internal.bots.sentinel.log_status", fake_status)
    monkeypatch.setattr("internal.bots.sentinel.build_evidence_report", fake_evidence)
    snapshot = collect_snapshot()
    assert evidence_calls
    report = observe(snapshot={**_healthy_snapshot(), "evidence": snapshot["evidence"]})
    events = [item[0] for item in calls]
    assert events.count("sentinel_predicate") == 10
    assert "status" in events
    assert "sentinel_health" in events
    assert "bot_observe" in events
    predicates_logged = [item[2]["predicate"] for item in calls if item[0] == "sentinel_predicate"]
    assert tuple(predicates_logged) == PREDICATE_NAMES
    assert report.evidence["status"] == "ok"


def test_observe_does_not_write_or_mutate(monkeypatch):
    writes = []
    real_open = open

    def guarded_open(path, mode="r", *args, **kwargs):
        text = str(mode)
        if any(flag in text for flag in ("w", "a", "x")) or ("+" in text):
            writes.append((str(path), text))
            raise AssertionError(f"Sentinel opened {path} for write mode={mode}")
        return real_open(path, mode, *args, **kwargs)

    monkeypatch.setattr("builtins.open", guarded_open)
    monkeypatch.setattr(
        "internal.worker_heartbeat.touch_heartbeat",
        lambda: (_ for _ in ()).throw(AssertionError("touch_heartbeat")),
    )
    monkeypatch.setattr(
        "internal.freshness.merge_remote_registry",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("merge_remote_registry")),
    )
    monkeypatch.setattr(
        "internal.freshness.refresh_all",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("refresh_all")),
    )
    monkeypatch.setattr(
        "internal.learning.predictions_store.save_predictions",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("save_predictions")),
    )

    snapshot = collect_snapshot()
    report = observe(snapshot=snapshot)
    assert writes == []
    assert report.audit["state_changing"] is False
    assert report.approval_required is False
    with pytest.raises(FrozenInstanceError):
        report.summary = "nope"  # type: ignore[misc]
    with pytest.raises(TypeError):
        report.predicates[0].freshness["status"] = "forged"


def test_latency_unknown_when_timing_absent():
    snap = _healthy_snapshot()
    snap.pop("latency_ms")
    result = _by_name(evaluate_predicates(snap, now=NOW))["latency"]
    assert result.status == STATUS_UNKNOWN
    assert result.reason == "no in-process health-path timing"


def test_malformed_scheduler_failures_do_not_crash():
    snap = _healthy_snapshot()
    snap["resolver"]["consecutive_failures"] = "n/a"
    snap["resolver"]["running"] = True
    snap.pop("loop_health")
    results = _by_name(evaluate_predicates(snap, now=NOW))
    assert results["scheduler"].status in FINDING_STATUSES
    assert results["resolver"].status == STATUS_UNKNOWN
    assert results["resolver"].reason
    assert "consecutive_failures" in results["resolver"].reason


def test_resolver_running_without_tick_is_unknown():
    snap = _healthy_snapshot()
    snap["resolver"] = {"running": True, "consecutive_failures": 0}
    snap["loop_health"]["resolver"] = {"running": True, "lifecycle": "running"}
    snap["loop_health"]["last_resolver_tick"] = None
    result = _by_name(evaluate_predicates(snap, now=NOW))["resolver"]
    assert result.status == STATUS_UNKNOWN
    assert result.reason == "resolver marked running but no last tick"


def test_worker_deferred_probe_is_unknown_not_alive():
    snap = _healthy_snapshot()
    snap["worker_peer"] = {
        "expected": True,
        "alive": None,
        "peer": "dedicated_worker",
        "source": "deferred",
    }
    result = _by_name(evaluate_predicates(snap, now=NOW))["worker"]
    assert result.status == STATUS_UNKNOWN
    assert result.reason
    assert result.freshness["status"] == "missing"
    _assert_freshness_aliases(result.freshness)
