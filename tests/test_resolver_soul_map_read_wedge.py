"""Regression: corrupt soul_map must not wedge resolver bootstrap reads."""

from __future__ import annotations

import json
import sys

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


def test_transient_soul_map_read_keeps_the_saved_cursor(tmp_path, monkeypatch):
    """A transient read fault at the soul_map_load stage must not reset the cursor."""
    from internal.store import soul_map_io

    soul = tmp_path / "soul_map.json"
    soul.write_text(
        json.dumps({"prediction_resolver_scheduler": {"round_robin_cursor": 42}}),
        encoding="utf-8",
    )
    ledger = tmp_path / "predictions.json"
    ledger.write_text(
        json.dumps({"predictions": [], "resolved": [],
                    "stats": {"correct": 0, "wrong": 0, "pending": 0}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(resolver, "PREDICTIONS_PATH", str(ledger))
    monkeypatch.setattr(weights, "SOUL_MAP_PATH", str(soul))

    provided = []
    injected = []

    def subnet_provider():
        provided.append(True)
        return [{"netuid": n} for n in range(49)]

    real_read = soul_map_io.read_blob_checked

    def flaky_read(path):
        # Fault the cycle's own cursor read, not the summary writer's read-for-write.
        from_writer = sys._getframe(1).f_code.co_name == "_read_for_write"
        if provided and not injected and not from_writer:
            injected.append(path)
            return soul_map_io.BlobRead("transient", None, error="busy")
        return real_read(path)

    monkeypatch.setattr(soul_map_io, "read_blob_checked", flaky_read)
    sched = resolver_scheduler.PredictionResolverScheduler(
        soul_map_path=str(soul), refresh_minutes=15, subnet_provider=subnet_provider
    )
    sched._run_refresh_cycle()

    assert injected, "the transient read was never injected"
    saved = json.loads(soul.read_text(encoding="utf-8"))
    assert saved["prediction_resolver_scheduler"]["round_robin_cursor"] == 42


def test_declined_persist_tick_records_success_and_refresh_backoff(monkeypatch):
    sched = resolver_scheduler.PredictionResolverScheduler(refresh_minutes=15)
    sched._active = True
    sched._backoff_minutes = 240
    sched._consecutive_failures = 3
    successes: list[dict] = []
    monkeypatch.setattr(sched.liveness, "record_skip", lambda reason: pytest.fail(reason))
    monkeypatch.setattr(sched.liveness, "record_success", lambda **kwargs: successes.append(kwargs))
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

    assert len(successes) == 1
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
