"""Regression: corrupt soul_map must not wedge resolver bootstrap reads."""

from __future__ import annotations

import json

import pytest

from internal.council import resolver, resolver_scheduler, weights
from internal.store.soul_map_io import WriteOutcome


def test_corrupt_soul_map_does_not_wedge_cycle_generation_seed(tmp_path, monkeypatch):
    soul = tmp_path / "soul_map.json"
    soul.write_text("not-json", encoding="utf-8")
    monkeypatch.setattr(weights, "SOUL_MAP_PATH", str(soul))

    sched = resolver_scheduler.PredictionResolverScheduler(
        soul_map_path=str(soul), refresh_minutes=15
    )
    sched._ensure_cycle_generation_seeded()
    assert sched._cycle_generation_seeded is False


def test_load_json_degrades_unreadable_to_empty_dict(tmp_path):
    soul = tmp_path / "soul_map.json"
    soul.write_text("{broken", encoding="utf-8")
    assert resolver_scheduler._load_json(str(soul)) == {}


def test_declined_persist_tick_records_skip_and_refresh_backoff(monkeypatch):
    sched = resolver_scheduler.PredictionResolverScheduler(refresh_minutes=15)
    sched._active = True
    sched._backoff_minutes = 240
    sched._consecutive_failures = 3
    skips: list[str] = []
    monkeypatch.setattr(sched.liveness, "record_skip", lambda reason: skips.append(reason))
    monkeypatch.setattr(sched.liveness, "record_success", lambda **_: pytest.fail("success"))
    monkeypatch.setattr(sched.liveness, "record_failure", lambda **_: pytest.fail("failure"))

    cycle = {"ok": True, "resolved_now": 2, "expired_now": 0, "pending": 0}
    sched._apply_persist_honesty(
        cycle,
        resolver_scheduler.PersistResult(outcome=WriteOutcome.DECLINED),
    )
    monkeypatch.setattr(
        sched, "_run_refresh_cycle_with_timeout", lambda: cycle
    )
    monkeypatch.setattr(sched, "_schedule_next", lambda *_a, **_k: None)
    monkeypatch.setattr(sched, "_persist_lifecycle_state", lambda: None)
    monkeypatch.setattr(sched, "_mark_first_tick", lambda _r: False)

    sched._tick(sync_manual=True)

    assert skips == ["persist_declined"]
    assert cycle.get("persist_outcome") == "declined"
    assert sched._backoff_minutes == 15
    assert sched._consecutive_failures == 0


def test_persist_honesty_preserves_existing_cycle_error():
    sched = resolver_scheduler.PredictionResolverScheduler(refresh_minutes=15)
    result = {"ok": True, "error": "resolve phase failed"}
    sched._apply_persist_honesty(
        result,
        resolver_scheduler.PersistResult(skipped_not_owner=True),
    )
    assert result["error"] == "resolve phase failed"
    assert result.get("skipped") == "persist_skipped"


def test_persist_refused_keeps_cycle_error_and_exposes_persist_outcome():
    from internal.store.soul_map_io import WriteOutcome

    sched = resolver_scheduler.PredictionResolverScheduler(refresh_minutes=15)
    result = {"ok": True, "error": "resolve phase failed"}
    sched._apply_persist_honesty(
        result,
        resolver_scheduler.PersistResult(
            outcome=WriteOutcome.UNREADABLE_BLOB, detail="sidecar=abc"
        ),
    )
    assert result["error"] == "resolve phase failed"
    assert result.get("persist_outcome") == "unreadable_blob"
    assert result["ok"] is False
