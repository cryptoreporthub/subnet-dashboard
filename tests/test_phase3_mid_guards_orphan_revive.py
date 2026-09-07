"""Phase 3: mid-guards, orphan persist bound, revive budget, dark-region telemetry."""

from __future__ import annotations

import json
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest

import internal.council.resolver as resolver
import internal.council.resolver_scheduler as resolver_scheduler
import internal.council.weights as weights


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(resolver, "PREDICTIONS_PATH", str(tmp_path / "predictions.json"))
    monkeypatch.setattr(resolver, "PRICE_CACHE_PATH", str(tmp_path / "price_cache.json"))
    soul = tmp_path / "soul_map.json"
    soul.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(weights, "SOUL_MAP_PATH", str(soul))
    monkeypatch.setattr(resolver_scheduler, "SOUL_MAP_PATH", str(soul))
    monkeypatch.setattr(
        "internal.learning.ledger_heal.heal_daily_pick_ledger",
        lambda dry_run=False: None,
    )
    monkeypatch.setattr(
        resolver,
        "resolve_due_predictions",
        lambda *_a, **_k: {
            "resolved_now": [],
            "expired_now": [],
            "stats": {"pending": 0},
            "watchdog": {"warning": False, "pending_count": 0},
        },
    )
    monkeypatch.setattr(
        resolver,
        "expire_stale_predictions",
        lambda: {
            "expired_now": [],
            "stats": {"pending": 0},
            "watchdog": {"warning": False, "pending_count": 0},
        },
    )

    @contextmanager
    def _free_slot(_name):
        yield True

    monkeypatch.setattr("internal.heavy_job_gate.heavy_job_slot", _free_slot)
    yield


def test_phase3_mid_guards_skip_resolve_and_expire_when_abandoned(monkeypatch):
    """Mid-guards: abandoned generation skips resolve_due / expire_stale bodies."""
    resolve_calls = {"n": 0}
    expire_calls = {"n": 0}
    entered_resolve = threading.Event()
    release = threading.Event()

    def _hang_resolve(*_a, **_k):
        resolve_calls["n"] += 1
        entered_resolve.set()
        release.wait(timeout=3)
        return {
            "resolved_now": [{"x": 1}],
            "expired_now": [],
            "stats": {"pending": 0},
            "watchdog": None,
        }

    def _count_expire():
        expire_calls["n"] += 1
        return {"expired_now": [], "stats": {"pending": 0}, "watchdog": None}

    monkeypatch.setattr(resolver, "resolve_due_predictions", _hang_resolve)
    monkeypatch.setattr(resolver, "expire_stale_predictions", _count_expire)
    monkeypatch.setattr(resolver_scheduler, "RESOLVER_FIRST_TICK_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(resolver_scheduler, "RESOLVER_CYCLE_TIMEOUT_SECONDS", 0.05)

    # Slow path: hang inside resolve so abandon fires mid-cycle; expire must not run.
    # Use full cycle path with first_tick False so budget is cycle timeout.
    sched = resolver_scheduler.PredictionResolverScheduler(
        refresh_minutes=1, subnet_provider=lambda: [{"netuid": 1}]
    )
    sched._active = True
    sched._first_tick_pending = False

    timed = sched._run_refresh_cycle_with_timeout()
    assert entered_resolve.wait(timeout=1)
    assert "cycle_timeout" in str(timed.get("error"))
    assert timed.get("enforced_budget_s") == 0.05
    # After abandon, orphan may still be in resolve; release it.
    release.set()
    time.sleep(0.1)
    # Expire body must not have been entered on the abandoned worker (or at most
    # zero after mid-guard). Hang was in resolve_due, so expire_calls stay 0.
    assert expire_calls["n"] == 0
    assert resolve_calls["n"] == 1


def test_phase3_orphan_bound_subsequent_tick_completes_persist(monkeypatch, tmp_path):
    """After abandon at ceiling, next tick completes persist (last_run advances)."""
    started = threading.Event()
    release = threading.Event()
    orphan_persist_attempts = {"n": 0}
    real_write = resolver_scheduler.write_soul_map

    def _slow_write(mutator, path):
        # Orphan that lost ownership should skip before write; if it reaches here
        # after revoke, still finish quickly. Block only while owning gen matches.
        orphan_persist_attempts["n"] += 1
        started.set()
        # Simulate long RMW only when still owner (pre-abandon); post-abandon
        # ownership gate should prevent most calls — if called with revoked
        # ownership the wrapper already skipped.
        release.wait(timeout=2)
        return real_write(mutator, path)

    # Hang in subnet_provider so timeout abandons before resolve; then orphan
    # tries persist_partial on stage finally — ownership must skip.
    def _blocked_provider():
        started.set()
        release.wait(timeout=3)
        return [{"netuid": 1}]

    monkeypatch.setattr(resolver_scheduler, "RESOLVER_FIRST_TICK_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(resolver_scheduler, "RESOLVER_CYCLE_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(resolver_scheduler, "write_soul_map", _slow_write)

    sched = resolver_scheduler.PredictionResolverScheduler(
        refresh_minutes=1, subnet_provider=_blocked_provider
    )
    sched._active = True
    sched._first_tick_pending = False

    first = sched._run_refresh_cycle_with_timeout()
    assert started.wait(timeout=1)
    assert "cycle_timeout" in str(first["error"])
    assert sched._persist_owner_gen is None

    # Release orphan; ownership gate must keep it from winning the next write.
    release.set()
    time.sleep(0.15)

    # Subsequent tick with fast provider must complete and advance last_run.
    sched._subnet_provider = lambda: [{"netuid": 1}]
    monkeypatch.setattr(resolver_scheduler, "write_soul_map", real_write)
    monkeypatch.setattr(resolver_scheduler, "RESOLVER_CYCLE_TIMEOUT_SECONDS", 30)
    monkeypatch.setattr(resolver_scheduler, "RESOLVER_FIRST_TICK_TIMEOUT_SECONDS", 30)

    second = sched._run_refresh_cycle_with_timeout()
    assert second.get("ok") is True
    assert second.get("skipped") != "cycle_in_flight"

    with open(weights.SOUL_MAP_PATH, "r", encoding="utf-8") as f:
        soul = json.load(f)
    last = soul["prediction_resolver_scheduler"]["last_cycle"]
    assert last.get("ok") is True
    assert last.get("run_at") == second.get("run_at")
    assert last.get("error") is None or "cycle_timeout" not in str(last.get("error"))

    # Scheduler state: next tick armed / last_run_ok path via tick
    sched._active = True
    tick = sched.run_once()
    assert tick.get("ok") is True
    state = sched.state()
    assert state.get("last_run_at") is not None
    # last_run_ok may be surfaced via liveness
    assert state.get("next_run_at") is not None or sched._next_run_at is not None


def test_phase3_revive_budget_uses_full_cycle_not_first_tick_cap(monkeypatch):
    """Boot revive sets full-budget flag so first post-revive tick uses cycle ceiling."""
    seen = {}

    def _capture(self):
        seen["first_tick_pending"] = self._first_tick_pending
        seen["revive_flag_before"] = bool(getattr(self, "_revive_use_full_budget", False))
        # Mimic timeout selection from production code
        use_full = bool(self._revive_use_full_budget) or not self._first_tick_pending
        timeout = (
            resolver_scheduler.RESOLVER_CYCLE_TIMEOUT_SECONDS
            if use_full
            else resolver_scheduler.RESOLVER_FIRST_TICK_TIMEOUT_SECONDS
        )
        seen["timeout"] = timeout
        if self._revive_use_full_budget:
            self._revive_use_full_budget = False
        return {
            "ok": True,
            "run_at": resolver_scheduler._now_iso(),
            "resolved_now": 0,
            "expired_now": 0,
            "pending": 0,
            "skipped": None,
        }

    monkeypatch.setattr(
        resolver_scheduler.PredictionResolverScheduler,
        "_run_refresh_cycle_with_timeout",
        _capture,
    )
    monkeypatch.setattr(resolver_scheduler, "RESOLVER_CYCLE_TIMEOUT_SECONDS", 120)
    monkeypatch.setattr(resolver_scheduler, "RESOLVER_FIRST_TICK_TIMEOUT_SECONDS", 90)

    resolver_scheduler.stop_prediction_resolver_scheduler()
    sched = resolver_scheduler.PredictionResolverScheduler(refresh_minutes=15)
    sched._active = True
    # Stale last_run so revive is willing
    old = (datetime.now(timezone.utc) - timedelta(hours=4)).isoformat().replace("+00:00", "Z")
    with open(weights.SOUL_MAP_PATH, "w", encoding="utf-8") as f:
        json.dump(
            {
                "prediction_resolver_scheduler": {
                    "last_cycle": {"run_at": old, "ok": True, "pending": 0},
                    "lifecycle": "stopped",
                }
            },
            f,
        )
    resolver_scheduler._scheduler = sched

    # Seed skip burst then revive must clear it
    sched.liveness._consecutive_skips = 5
    sched.liveness._consecutive_failures = 3

    try:
        out = resolver_scheduler.revive_prediction_resolver_scheduler(force=True)
        assert out.get("recycled") is True
        # After recycle, new scheduler instance may be started — grab active
        armed = resolver_scheduler._scheduler
        assert armed is not None
        assert armed.liveness._consecutive_skips == 0
        assert armed.liveness._consecutive_failures == 0
        # Budget selection on the revive run_once path
        assert seen.get("timeout") == 120
        # Flag consumed
        assert armed._revive_use_full_budget is False
        assert armed.state().get("next_run_at") is not None or armed._next_run_at is not None
    finally:
        resolver_scheduler.stop_prediction_resolver_scheduler()


def test_phase3_dark_region_telemetry_t1_5_and_persist_subtimers(monkeypatch):
    """t1_5 + persist subtimers; rmw/mutator split must be able to diverge."""
    real_write = resolver_scheduler.write_soul_map

    def _write_with_post_mutator_io(mutator, path=None):
        # Sleep AFTER the timed mutator returns but still inside write_soul_map's
        # mutator callback slot → inflates RMW wall, not mutator body.
        def outer(blob):
            mutator(blob)
            time.sleep(0.05)

        return real_write(outer, path)

    monkeypatch.setattr(resolver_scheduler, "write_soul_map", _write_with_post_mutator_io)

    sched = resolver_scheduler.PredictionResolverScheduler(
        refresh_minutes=1, subnet_provider=lambda: [{"netuid": 1}]
    )
    sched._active = True
    sched._first_tick_pending = False
    result = sched._run_refresh_cycle_with_timeout()
    assert result.get("ok") is True
    gap = result.get("gap_timing_ms") or {}
    assert gap.get("t1") is not None
    assert gap.get("t1_5") is not None
    assert gap.get("t2") is not None
    assert gap["t1"] <= gap["t1_5"] <= gap["t2"]
    assert "persist_apply_cycle_timing_ms" in gap
    assert "persist_summary_rmw_ms" in gap
    assert "persist_summary_mutator_ms" in gap
    assert "persist_write_ms" not in gap
    assert gap["persist_apply_cycle_timing_ms"] >= 0
    rmw = float(gap["persist_summary_rmw_ms"])
    mut = float(gap["persist_summary_mutator_ms"])
    assert rmw >= mut
    # 50ms injected I/O must show up in the RMW−mutator delta (fail if double-count).
    assert (rmw - mut) >= 40.0
    assert result.get("enforced_budget_s") is None or isinstance(
        result.get("enforced_budget_s"), (int, float)
    )


def test_phase3_timeout_label_reports_enforced_budget(monkeypatch):
    """Timeout error label uses the enforced local timeout budget."""
    started = threading.Event()
    release = threading.Event()

    def _blocked_provider():
        started.set()
        release.wait(timeout=2)
        return []

    monkeypatch.setattr(resolver_scheduler, "RESOLVER_FIRST_TICK_TIMEOUT_SECONDS", 0.07)
    monkeypatch.setattr(resolver_scheduler, "RESOLVER_CYCLE_TIMEOUT_SECONDS", 0.07)
    sched = resolver_scheduler.PredictionResolverScheduler(
        refresh_minutes=1, subnet_provider=_blocked_provider
    )
    sched._active = True
    sched._first_tick_pending = False
    out = sched._run_refresh_cycle_with_timeout()
    assert started.wait(timeout=1)
    assert out["error"] == "cycle_timeout_0.07s"
    assert out["enforced_budget_s"] == 0.07
    release.set()
