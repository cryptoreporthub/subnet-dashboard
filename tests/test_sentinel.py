"""Sentinel bot: predicate evaluation, immutable reports, read-only observe."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from internal.bots.sentinel import (
    BOT_NAME,
    PREDICATE_NAMES,
    HealthReport,
    collect_snapshot,
    evaluate_predicates,
    observe,
)
from internal.ops.bot_policy import classify_freshness


NOW = datetime(2026, 8, 27, tzinfo=timezone.utc)
CHECKED = "2026-08-27T00:00:00Z"


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


def test_sentinel_module_is_importable():
    import internal.bots.sentinel as sentinel

    assert sentinel.BOT_NAME == "sentinel"
    assert sentinel.PREDICATE_NAMES == PREDICATE_NAMES
    assert len(PREDICATE_NAMES) == 10


def test_health_report_is_frozen():
    report = observe(snapshot=_healthy_snapshot())
    assert isinstance(report, HealthReport)
    with pytest.raises(FrozenInstanceError):
        report.status = "mutated"  # type: ignore[misc]
    with pytest.raises(TypeError):
        report.freshness["status"] = "forged"
    with pytest.raises(TypeError):
        report.evidence["status"] = "forged"


def test_report_includes_policy_2_2_freshness_fields():
    report = observe(snapshot=_healthy_snapshot())
    freshness = report.freshness
    assert freshness["status"] in {"fresh", "aging", "stale", "missing", "degraded"}
    assert "observed_at" in freshness
    assert "age_seconds" in freshness
    assert "sources" in freshness
    assert freshness["sources"]
    for envelope in freshness["sources"]:
        assert envelope["source"]
        assert envelope["status"] in {"fresh", "aging", "stale", "missing", "degraded"}
        assert "captured_at" in envelope
        assert "age_seconds" in envelope
        assert "authoritative" in envelope
        assert "thresholds_seconds" in envelope


def test_ten_predicates_evaluate_healthy_snapshot():
    results = _by_name(evaluate_predicates(_healthy_snapshot(), now=NOW))
    assert tuple(results) == PREDICATE_NAMES
    for name in PREDICATE_NAMES:
        assert results[name].status == "ok", name
    report = observe(snapshot=_healthy_snapshot())
    assert report.status == "ok"
    assert report.bot == BOT_NAME
    assert report.approval_required is False
    assert report.approval["status"] == "not_required"
    assert report.recommended_action is None
    assert report.confidence == 1.0


def test_missing_signals_are_unknown_not_fabricated():
    results = _by_name(evaluate_predicates({}, now=NOW))
    assert tuple(results) == PREDICATE_NAMES
    for name, item in results.items():
        assert item.status == "unknown", name
        assert item.freshness["status"] in {"missing", "degraded"}
    report = observe(snapshot={})
    assert report.status == "degraded"
    assert set(report.unknowns) == set(PREDICATE_NAMES)


def test_failing_predicates_use_real_snapshot_fields():
    snap = _healthy_snapshot()
    snap["liveness"]["live"] = False
    snap["liveness"]["status"] = "down"
    snap["latency_ms"] = 2500.0
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
        assert results[name].status == "fail", name


def test_observe_uses_evidence_and_notify(monkeypatch):
    calls = []
    evidence_calls = []

    def fake_notify(event, message="", **kwargs):
        calls.append((event, message, kwargs))

    def fake_evidence():
        evidence_calls.append(True)
        return {"status": "ok", "alerts": [], "evidence_sources": []}

    monkeypatch.setattr("internal.bots.sentinel.log_event", fake_notify)
    monkeypatch.setattr("internal.bots.sentinel.build_evidence_report", fake_evidence)
    snapshot = collect_snapshot()
    assert evidence_calls
    report = observe(snapshot={**_healthy_snapshot(), "evidence": snapshot["evidence"]})
    events = [item[0] for item in calls]
    assert "sentinel_health" in events
    assert "bot_observe" in events
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
    monkeypatch.setattr("fetchers.taomarketcap.init_db", lambda: None)
    monkeypatch.setattr(
        "internal.subnets.feed.probe_feed_layers",
        lambda: {
            "effective_source": "blockmachine",
            "likely_total": 1,
            "live_cache": {},
        },
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
    assert result.status == "unknown"


def test_worker_deferred_probe_is_unknown_not_alive():
    snap = _healthy_snapshot()
    snap["worker_peer"] = {
        "expected": True,
        "alive": None,
        "peer": "dedicated_worker",
        "source": "deferred",
    }
    result = _by_name(evaluate_predicates(snap, now=NOW))["worker"]
    assert result.status == "unknown"
    assert result.freshness["status"] == "missing"
