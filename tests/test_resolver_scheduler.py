"""
Tests for the prediction resolver scheduler and the stale-prediction expiry
safety net.

Covers:
- ``resolver.expire_stale_predictions`` edge cases (not-yet-due, within grace,
  past grace, corrupt records)
- ``resolver._compute_stats`` excludes expired entries from accuracy
- ``resolver_scheduler.PredictionResolverScheduler`` lifecycle: start/stop,
  idempotency, single-cycle run, backoff on failure, cycle-summary persistence
- Module-level singleton helpers
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List

import pytest

import internal.council.resolver as resolver
import internal.council.resolver_scheduler as resolver_scheduler
import internal.council.weights as weights


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def isolate_data_paths(tmp_path, monkeypatch):
    """Keep all persistence inside a temp directory."""
    monkeypatch.setattr(resolver, "PREDICTIONS_PATH", str(tmp_path / "predictions.json"))
    monkeypatch.setattr(resolver, "PRICE_CACHE_PATH", str(tmp_path / "price_cache.json"))
    monkeypatch.setattr(weights, "SOUL_MAP_PATH", str(tmp_path / "soul_map.json"))
    monkeypatch.setattr(resolver_scheduler, "SOUL_MAP_PATH", str(tmp_path / "soul_map.json"))


@pytest.fixture(autouse=True)
def _reset_prediction_resolver_singleton():
    """Drop module singleton between tests so lifecycle does not leak."""
    resolver_scheduler.stop_prediction_resolver_scheduler()
    yield
    resolver_scheduler.stop_prediction_resolver_scheduler()


@pytest.fixture
def nudge_spy(monkeypatch):
    """Capture weight nudges without touching the filesystem."""
    calls: List[Any] = []

    def _fake_nudge(correct, expert, **_kwargs):
        calls.append((correct, expert))

    monkeypatch.setattr(resolver, "_nudge_weights", _fake_nudge)
    return calls


def _iso(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


def _write_predictions(data: Dict[str, Any]) -> None:
    with open(resolver.PREDICTIONS_PATH, "w") as f:
        json.dump(data, f)


# ---------------------------------------------------------------------------
# Expiry logic
# ---------------------------------------------------------------------------

def test_expire_does_not_touch_not_yet_due_predictions():
    now = datetime.now(timezone.utc)
    _write_predictions({
        "predictions": [
            {
                "netuid": 1,
                "reference_price": 100.0,
                "predicted_pct": 10.0,
                "direction": "up",
                "expert": "quant",
                "horizon_hours": 24,
                "resolve_at": _iso(now + timedelta(hours=1)),
            },
        ],
        "resolved": [],
    })

    result = resolver.expire_stale_predictions()
    assert result["expired_now"] == []
    assert len(result["pending"]) == 1
    assert result["stats"]["pending"] == 1
    assert result["stats"]["expired"] == 0


def test_expire_keeps_predictions_within_grace_window():
    """A prediction just past ``resolve_at`` but within the grace window must
    stay pending -- the price feed may still recover."""
    now = datetime.now(timezone.utc)
    horizon = 24.0
    grace = horizon * resolver._EXPIRY_GRACE_MULTIPLE
    resolve_at = now - timedelta(hours=1)
    _write_predictions({
        "predictions": [
            {
                "netuid": 1,
                "reference_price": 100.0,
                "predicted_pct": 10.0,
                "direction": "up",
                "expert": "quant",
                "horizon_hours": horizon,
                "resolve_at": _iso(resolve_at),
            },
        ],
        "resolved": [],
    })

    result = resolver.expire_stale_predictions()
    assert result["expired_now"] == []
    assert len(result["pending"]) == 1


def test_expire_retires_predictions_past_grace_window():
    now = datetime.now(timezone.utc)
    horizon = 24.0
    grace = horizon * resolver._EXPIRY_GRACE_MULTIPLE
    resolve_at = now - timedelta(hours=grace + 5)
    _write_predictions({
        "predictions": [
            {
                "netuid": 1,
                "reference_price": 100.0,
                "predicted_pct": 10.0,
                "direction": "up",
                "expert": "quant",
                "horizon_hours": horizon,
                "resolve_at": _iso(resolve_at),
                # Retry cap spent, so expiry does not depend on the lookup retries.
                "resolve_attempts": resolver._PRICE_RETRY_CAP,
            },
        ],
        "resolved": [],
    })

    result = resolver.expire_stale_predictions()
    assert len(result["expired_now"]) == 1
    expired = result["expired_now"][0]
    assert expired["status"] == "expired"
    assert expired["outcome"] == "expired"
    assert expired["correct"] is None
    assert result["stats"]["expired"] == 1
    assert result["stats"]["pending"] == 0


def test_expire_handles_corrupt_resolve_at():
    """A prediction with an unparseable resolve_at is retired, not crashed on."""
    _write_predictions({
        "predictions": [
            {
                "netuid": 1,
                "reference_price": 100.0,
                "predicted_pct": 10.0,
                "direction": "up",
                "expert": "quant",
                "horizon_hours": 24,
                "resolve_at": "not-a-date",
            },
        ],
        "resolved": [],
    })

    result = resolver.expire_stale_predictions()
    assert len(result["expired_now"]) == 1
    assert result["expired_now"][0]["status"] == "expired"


def test_resolver_accepts_offset_plus_z_timestamp():
    now = datetime.now(timezone.utc)
    _write_predictions({
        "predictions": [
            {
                "netuid": 1,
                "reference_price": 100.0,
                "predicted_pct": 10.0,
                "direction": "up",
                "expert": "quant",
                "horizon_hours": 24,
                "resolve_at": (now + timedelta(hours=1)).isoformat() + "Z",
            },
        ],
        "resolved": [],
    })

    result = resolver.expire_stale_predictions()
    assert len(result["pending"]) == 1
    assert result["expired_now"] == []


def test_resolve_due_restores_recently_expired_malformed_timestamp():
    now = datetime.now(timezone.utc)
    _write_predictions({
        "predictions": [],
        "resolved": [
            {
                "id": "malformed-horizon",
                "netuid": 1,
                "reference_price": 100.0,
                "predicted_pct": 10.0,
                "direction": "up",
                "expert": "quant",
                "horizon_hours": 24,
                "resolve_at": (now + timedelta(hours=1)).isoformat() + "Z",
                "status": "expired",
                "outcome": "expired",
                "correct": None,
                "resolved_at": now.isoformat().replace("+00:00", "Z"),
            },
        ],
    })

    result = resolver.resolve_due_predictions(subnets=[])
    assert [row["id"] for row in result["restored_now"]] == ["malformed-horizon"]
    assert len(result["pending"]) == 1
    assert result["pending"][0]["status"] == "pending"
    assert result["pending"][0]["resolve_at"].endswith("Z")
    assert not result["pending"][0]["resolve_at"].endswith("+00:00Z")
    assert all(row.get("outcome") != "expired" for row in result["pending"])


def test_expire_skips_non_dict_records():
    """A corrupt non-dict entry must not crash the loop."""
    now = datetime.now(timezone.utc)
    _write_predictions({
        "predictions": [
            "i am not a dict",
            42,
            {
                "netuid": 1,
                "horizon_hours": 24,
                "resolve_at": _iso(now - timedelta(hours=100)),
                # Retry cap spent, so expiry does not depend on the lookup retries.
                "resolve_attempts": resolver._PRICE_RETRY_CAP,
            },
        ],
        "resolved": [],
    })

    result = resolver.expire_stale_predictions()
    assert len(result["expired_now"]) == 1
    assert result["stats"]["pending"] == 0


def test_expire_does_not_nudge_weights(nudge_spy):
    """Expired predictions carry no outcome -> expert weights must not move."""
    now = datetime.now(timezone.utc)
    _write_predictions({
        "predictions": [
            {
                "netuid": 1,
                "horizon_hours": 24,
                "expert": "quant",
                "resolve_at": _iso(now - timedelta(hours=100)),
            },
        ],
        "resolved": [],
    })

    resolver.expire_stale_predictions()
    assert nudge_spy == []


def test_compute_stats_excludes_expired_from_accuracy():
    data = {
        "predictions": [],
        "resolved": [
            {"correct": True},
            {"correct": False},
            {"correct": None, "outcome": "expired"},
            {"correct": None, "outcome": "expired"},
        ],
    }
    _write_predictions(data)

    result = resolver.get_resolved_predictions()
    stats = result["stats"]
    assert stats["correct"] == 1
    assert stats["wrong"] == 1
    assert stats["expired"] == 2
    assert stats["accuracy"] == round(1 / 2, 3)


def test_resolve_due_predictions_expires_when_no_price(nudge_spy):
    """A due prediction with no price and past grace is expired, not stuck."""
    now = datetime.now(timezone.utc)
    horizon = 24.0
    grace = horizon * resolver._EXPIRY_GRACE_MULTIPLE
    _write_predictions({
        "predictions": [
            {
                "netuid": 999,
                "reference_price": 100.0,
                "predicted_pct": 10.0,
                "direction": "up",
                "expert": "quant",
                "horizon_hours": horizon,
                "resolve_at": _iso(now - timedelta(hours=grace + 5)),
                # Retry cap spent, so expiry does not depend on the lookup retries.
                "resolve_attempts": resolver._PRICE_RETRY_CAP,
            },
        ],
        "resolved": [],
    })

    result = resolver.resolve_due_predictions(subnets=[])
    assert len(result.get("expired_now", [])) == 1
    assert result["expired_now"][0]["status"] == "expired"
    assert result["pending"] == []
    assert nudge_spy == []


def test_resolve_due_predictions_keeps_due_no_price_within_grace():
    """Due + no price but within grace -> stays pending (price may recover)."""
    now = datetime.now(timezone.utc)
    _write_predictions({
        "predictions": [
            {
                "netuid": 999,
                "horizon_hours": 24,
                "resolve_at": _iso(now - timedelta(hours=1)),
            },
        ],
        "resolved": [],
    })

    result = resolver.resolve_due_predictions(subnets=[])
    assert result.get("expired_now", []) == []
    assert len(result["pending"]) == 1


# ---------------------------------------------------------------------------
# Scheduler lifecycle
# ---------------------------------------------------------------------------

@pytest.fixture
def fresh_scheduler(monkeypatch):
    """Reset the module-level singleton between tests."""
    monkeypatch.setattr(resolver_scheduler, "_scheduler", None)
    yield
    sched = resolver_scheduler.get_prediction_resolver_scheduler()
    if sched is not None:
        sched.stop()


def _static_subnets():
    return [{"netuid": 1, "price": 110.0}]


def test_scheduler_start_stop(fresh_scheduler):
    sched = resolver_scheduler.PredictionResolverScheduler(
        refresh_minutes=1, subnet_provider=_static_subnets
    )
    state = sched.state()
    assert state["running"] is False

    sched.start()
    assert sched.state()["running"] is True
    assert sched.state()["next_run_at"] is not None
    assert sched.state()["lifecycle"] == "scheduled"
    assert sched.state()["first_tick_scheduled_at"] is not None

    sched.stop()
    assert sched.state()["running"] is False
    assert sched.state()["next_run_at"] is None


def test_scheduler_start_is_idempotent(fresh_scheduler):
    sched = resolver_scheduler.PredictionResolverScheduler(
        refresh_minutes=1, subnet_provider=_static_subnets
    )
    first = sched.start()
    assert first["started"] is True
    second = sched.start()
    assert second["started"] is False
    sched.stop()


def test_scheduler_run_once_resolves_due_predictions(nudge_spy, fresh_scheduler, tmp_path):
    now = datetime.now(timezone.utc)
    _write_predictions({
        "predictions": [
            {
                # council_published population + attributable signal evidence
                # (the rogue guard rejects bare expert stamps), so the weight
                # nudge fires for the stamped expert.
                "pick_source": "council",
                "signal_source": "emission_momentum",
                "netuid": 1,
                "reference_price": 100.0,
                "predicted_pct": 10.0,
                "direction": "up",
                "expert": "quant",
                "resolve_at": _iso(now - timedelta(hours=1)),
            },
        ],
        "resolved": [],
    })

    # Hourly OHLCV is the canonical grading source; hydrate the cache the
    # autouse fixture points resolver at so this test grades deterministically
    # instead of depending on spot-price fallback behavior.
    (tmp_path / "price_cache.json").write_text(
        json.dumps(
            {
                "1": {
                    "candles": [
                        {
                            "timestamp": _iso(now - timedelta(hours=1)),
                            "close": 115.0,
                            "volume": 10.0,
                        }
                    ]
                }
            }
        )
    )

    sched = resolver_scheduler.PredictionResolverScheduler(
        refresh_minutes=1, subnet_provider=_static_subnets
    )
    result = sched.run_once()

    assert result["ok"] is True
    assert result["resolved_now"] == 1
    assert result["error"] is None
    assert nudge_spy == [(True, "quant")]

    state = sched.state()
    assert state["last_run_ok"] is True
    assert state["last_resolved"] == 1
    assert state["consecutive_failures"] == 0


def test_scheduler_run_once_expires_stale_predictions(fresh_scheduler):
    now = datetime.now(timezone.utc)
    horizon = 24.0
    grace = horizon * resolver._EXPIRY_GRACE_MULTIPLE
    _write_predictions({
        "predictions": [
            {
                "netuid": 999,
                "horizon_hours": horizon,
                "expert": "quant",
                "resolve_at": _iso(now - timedelta(hours=grace + 5)),
                # Retry cap spent, so expiry does not depend on the lookup retries.
                "resolve_attempts": resolver._PRICE_RETRY_CAP,
            },
        ],
        "resolved": [],
    })

    sched = resolver_scheduler.PredictionResolverScheduler(
        refresh_minutes=1, subnet_provider=lambda: []
    )
    result = sched.run_once()

    assert result["ok"] is True
    assert result["expired_now"] == 1
    assert result["resolved_now"] == 0
    assert sched.state()["last_expired"] == 1


def _ledger_row(pred_id: str) -> Dict[str, Any]:
    with open(resolver.PREDICTIONS_PATH) as f:
        ledger = json.load(f)
    rows = [
        row
        for key in ("predictions", "resolved")
        for row in ledger.get(key, [])
        if row.get("id") == pred_id
    ]
    assert len(rows) == 1
    return rows[0]


def test_scheduler_cycles_spend_the_retry_budget_then_expire(fresh_scheduler, monkeypatch):
    """Resolve and expire run back to back in one cycle. A past-grace row with
    no price must still get its full lookup budget across real cycles, then be
    retired: not retired early by the expire stage, and not left pending."""
    now = datetime.now(timezone.utc)
    grace = 24.0 * resolver._EXPIRY_GRACE_MULTIPLE
    _write_predictions({
        "predictions": [
            {
                "id": "pred-combined",
                "netuid": 999,
                "reference_price": 100.0,
                "predicted_pct": 10.0,
                "direction": "up",
                "expert": "quant",
                "horizon_hours": 24.0,
                "resolve_at": _iso(now - timedelta(hours=grace + 5)),
            },
        ],
        "resolved": [],
    })
    lookups = {"n": 0}

    def _no_price(*_args, **_kwargs):
        lookups["n"] += 1
        return ("ungradeable", 0.0, {"candles_in_window": 0, "price_source": None})

    monkeypatch.setattr(resolver, "price_at_resolve_at", _no_price, raising=False)
    sched = resolver_scheduler.PredictionResolverScheduler(
        refresh_minutes=1, subnet_provider=lambda: []
    )

    cap = resolver._PRICE_RETRY_CAP
    history = []
    for _ in range(cap + 2):
        assert sched.run_once()["ok"] is True
        status = _ledger_row("pred-combined")["status"]
        history.append((status, lookups["n"]))
        if status == "expired":
            break

    # One lookup per cycle, pending until the cap-th lookup, retired in that
    # same cycle. Later cycles re-read expired rows through
    # regrade_expired_predictions, a separate recovery sweep not pinned here.
    assert history == [("pending", n) for n in range(1, cap)] + [("expired", cap)]
    row = _ledger_row("pred-combined")
    assert row["retirement_reason"] == "missing_price_at_horizon"
    assert row["resolve_attempts"] == cap


def test_scheduler_backoff_on_failure(fresh_scheduler):
    """A failing subnet provider triggers exponential backoff, not a crash."""
    def _failing_provider():
        raise RuntimeError("price feed down")

    sched = resolver_scheduler.PredictionResolverScheduler(
        refresh_minutes=5, max_backoff_minutes=240, subnet_provider=_failing_provider
    )
    result = sched.run_once()

    assert result["ok"] is False
    assert "price feed down" in (result["error"] or "")
    state = sched.state()
    assert state["last_run_ok"] is False
    assert state["consecutive_failures"] == 1
    assert state["backoff_minutes"] == 10


def test_scheduler_backoff_caps_at_max(fresh_scheduler):
    def _failing_provider():
        raise RuntimeError("boom")

    sched = resolver_scheduler.PredictionResolverScheduler(
        refresh_minutes=5, max_backoff_minutes=20, subnet_provider=_failing_provider
    )
    for _ in range(10):
        sched.run_once()

    state = sched.state()
    assert state["backoff_minutes"] <= 20
    assert state["consecutive_failures"] == 10


def test_scheduler_persists_cycle_summary(fresh_scheduler):
    now = datetime.now(timezone.utc)
    _write_predictions({
        "predictions": [
            {
                "netuid": 1,
                "reference_price": 100.0,
                "predicted_pct": 10.0,
                "direction": "up",
                "expert": "quant",
                "resolve_at": _iso(now - timedelta(hours=1)),
            },
        ],
        "resolved": [],
    })

    sched = resolver_scheduler.PredictionResolverScheduler(
        refresh_minutes=1, subnet_provider=_static_subnets
    )
    sched.run_once()

    with open(weights.SOUL_MAP_PATH, "r") as f:
        soul = json.load(f)
    summary = soul["prediction_resolver_scheduler"]["last_cycle"]
    assert summary["ok"] is True
    assert summary["resolved_now"] == 1
    assert summary["pending"] == 0


def test_scheduler_persists_stage_timing_evidence(monkeypatch, fresh_scheduler):
    monkeypatch.setattr(
        "internal.learning.ledger_heal.heal_daily_pick_ledger",
        lambda dry_run=False: None,
    )
    monkeypatch.setattr(
        resolver,
        "resolve_due_predictions",
        lambda _subnets: {
            "resolved_now": [],
            "expired_now": [],
            "stats": {"pending": 0},
            "watchdog": {},
        },
    )
    monkeypatch.setattr(
        resolver,
        "expire_stale_predictions",
        lambda: {"expired_now": [], "stats": {"pending": 0}, "watchdog": {}},
    )
    monkeypatch.setattr(
        "internal.calibration.scheduler.maybe_trigger_auto_retrain",
        lambda resolved_now: {"triggered": False},
    )

    sched = resolver_scheduler.PredictionResolverScheduler(
        refresh_minutes=1, subnet_provider=lambda: []
    )
    result = sched.run_once()

    assert result["ok"] is True
    with open(weights.SOUL_MAP_PATH, "r") as f:
        soul = json.load(f)
    summary = soul["prediction_resolver_scheduler"]["last_cycle"]
    timing = summary["stage_timing_ms"]
    assert {
        "ledger_heal_ms",
        "soul_map_load_ms",
        "resolve_due_ms",
        "tmc_lock_wait_ms",
        "hydrate_ms_total",
        "hydrate_ms_max",
        "hydration_count",
        "total_cycle_ms",
    } <= timing.keys()
    assert all(isinstance(timing[key], (int, float)) for key in timing)
    assert summary["active_stage"] is None
    assert summary["abandoned_live"] == 0


def test_scheduler_recovers_after_failure(nudge_spy, fresh_scheduler):
    """Backoff resets to the normal cadence once a cycle succeeds again."""
    state = {"fail": True}

    def _flaky_provider():
        if state["fail"]:
            raise RuntimeError("transient")
        return [{"netuid": 1, "price": 110.0}]

    now = datetime.now(timezone.utc)
    _write_predictions({
        "predictions": [
            {
                "netuid": 1,
                "reference_price": 100.0,
                "predicted_pct": 10.0,
                "direction": "up",
                "expert": "quant",
                "resolve_at": _iso(now - timedelta(hours=1)),
            },
        ],
        "resolved": [],
    })

    sched = resolver_scheduler.PredictionResolverScheduler(
        refresh_minutes=5, subnet_provider=_flaky_provider
    )
    failed = sched.run_once()
    assert failed["ok"] is False
    assert sched.state()["consecutive_failures"] == 1

    state["fail"] = False
    ok = sched.run_once()
    assert ok["ok"] is True
    assert sched.state()["consecutive_failures"] == 0
    assert sched.state()["backoff_minutes"] == 5


# ---------------------------------------------------------------------------
# Module-level singleton helpers
# ---------------------------------------------------------------------------

def test_singleton_start_stop_state(fresh_scheduler):
    start = resolver_scheduler.start_prediction_resolver_scheduler(
        refresh_minutes=1, immediate=False, subnet_provider=_static_subnets
    )
    assert start["started"] is True

    state = resolver_scheduler.get_prediction_resolver_scheduler_state()
    assert state["running"] is True

    stop = resolver_scheduler.stop_prediction_resolver_scheduler()
    assert stop["stopped"] is True

    state = resolver_scheduler.get_prediction_resolver_scheduler_state()
    assert state["running"] is False


def test_singleton_state_when_not_started(fresh_scheduler):
    state = resolver_scheduler.get_prediction_resolver_scheduler_state()
    assert state["running"] is False
    assert state["last_run_at"] is None


def test_default_subnets_fallback_returns_list():
    """The default subnet provider must never raise -- it returns a list."""
    result = resolver_scheduler._default_subnets()
    assert isinstance(result, list)


def test_default_subnets_uses_worker_cache(monkeypatch):
    monkeypatch.setattr(
        "internal.live_subnets.get_live_subnets",
        lambda: [{"netuid": 7, "price": 1.0}],
    )
    result = resolver_scheduler._default_subnets()
    assert result[0]["netuid"] == 7


def test_default_subnets_falls_back_to_registry_when_cache_read_fails(monkeypatch):
    monkeypatch.setattr(
        "internal.live_subnets.get_live_subnets",
        lambda: (_ for _ in ()).throw(RuntimeError("cache unavailable")),
    )
    monkeypatch.setattr(
        "internal.subnets.feed.registry_subnet_rows",
        lambda: [{"netuid": 3, "price": 1.0}],
    )
    result = resolver_scheduler._default_subnets()
    assert result[0]["netuid"] == 3


# ---------------------------------------------------------------------------
# G11 — round-robin batching
# ---------------------------------------------------------------------------

def test_round_robin_batch_sorts_by_netuid():
    subnets = [
        {"netuid": 3, "price": 3.0},
        {"netuid": 1, "price": 1.0},
        {"netuid": 2, "price": 2.0},
    ]
    batch, _ = resolver_scheduler._round_robin_batch(subnets, 0, 2)
    assert [sn["netuid"] for sn in batch] == [1, 2]


def test_round_robin_batch_wraps_cursor():
    subnets = [{"netuid": i, "price": float(i)} for i in range(1, 6)]
    batch, next_cursor = resolver_scheduler._round_robin_batch(subnets, 4, 3)
    assert [sn["netuid"] for sn in batch] == [5, 1, 2]
    assert next_cursor == 2


def test_round_robin_batch_caps_at_subnet_count():
    subnets = [{"netuid": 1, "price": 1.0}, {"netuid": 2, "price": 2.0}]
    batch, next_cursor = resolver_scheduler._round_robin_batch(subnets, 0, 32)
    assert len(batch) == 2
    assert next_cursor == 0


def test_scheduler_persists_round_robin_cursor(fresh_scheduler):
    subnets = [{"netuid": i, "price": float(i)} for i in range(1, 11)]

    sched = resolver_scheduler.PredictionResolverScheduler(
        refresh_minutes=1, subnet_provider=lambda: subnets
    )
    sched.run_once()

    with open(weights.SOUL_MAP_PATH, "r") as f:
        soul = json.load(f)
    sched_state = soul["prediction_resolver_scheduler"]
    n = len(subnets)
    batch_size = min(resolver_scheduler.RESOLVER_BATCH_SIZE, n)
    assert sched_state["last_cycle"]["batch_size"] == batch_size
    assert sched_state["round_robin_cursor"] == batch_size % n


def test_scheduler_passes_full_subnet_list_to_resolve(monkeypatch, fresh_scheduler):
    subnets = [{"netuid": i, "price": float(i)} for i in range(1, 51)]
    seen = {}

    def _spy_resolve(subnet_list):
        seen["subnet_len"] = len(subnet_list)
        return {
            "resolved_now": [],
            "expired_now": [],
            "stats": {"pending": 0},
            "watchdog": {},
        }

    monkeypatch.setattr(resolver, "resolve_due_predictions", _spy_resolve)
    monkeypatch.setattr(resolver_scheduler, "RESOLVER_BATCH_SIZE", 8)

    sched = resolver_scheduler.PredictionResolverScheduler(
        refresh_minutes=1, subnet_provider=lambda: subnets
    )
    sched.run_once()

    assert seen["subnet_len"] == 50


def test_scheduler_skip_persists_last_cycle_when_heavy_job_busy(monkeypatch, fresh_scheduler):
    from contextlib import contextmanager

    @contextmanager
    def _always_busy(_name):
        yield False

    monkeypatch.setattr("internal.heavy_job_gate.heavy_job_slot", _always_busy)
    sched = resolver_scheduler.PredictionResolverScheduler(
        refresh_minutes=1, subnet_provider=lambda: [{"netuid": 1, "price": 1.0}]
    )
    sched._active = True
    sched._tick()

    with open(weights.SOUL_MAP_PATH, "r") as f:
        soul = json.load(f)
    last = soul["prediction_resolver_scheduler"]["last_cycle"]
    assert last.get("skipped") == "heavy_job_busy"
    assert last.get("run_at")
    assert sched.liveness.snapshot().get("last_event_at") is not None
    # Inverted laundering contract: a skip burst must NOT read as healthy.
    snap = sched.liveness.snapshot()
    assert snap["status"] != "ok"
    assert snap["consecutive_skips"] >= 1


def test_resolver_cycle_times_out(monkeypatch, fresh_scheduler, caplog):
    import time

    def _hang(self):
        time.sleep(5)
        return {
            "ok": True,
            "run_at": _now_iso(),
            "resolved_now": 0,
            "expired_now": 0,
            "pending": 0,
        }

    from internal.council.resolver_scheduler import _now_iso

    monkeypatch.setattr(resolver_scheduler, "RESOLVER_CYCLE_TIMEOUT_SECONDS", 1)
    monkeypatch.setattr(resolver_scheduler, "RESOLVER_FIRST_TICK_TIMEOUT_SECONDS", 1)
    monkeypatch.setattr(
        resolver_scheduler.PredictionResolverScheduler,
        "_run_refresh_cycle",
        _hang,
    )
    sched = resolver_scheduler.PredictionResolverScheduler(
        refresh_minutes=1, subnet_provider=lambda: [{"netuid": 1, "price": 1.0}]
    )
    sched._active = True
    sched._first_tick_pending = True
    sched._tick()
    with open(weights.SOUL_MAP_PATH, "r") as f:
        soul = json.load(f)
    last = soul["prediction_resolver_scheduler"]["last_cycle"]
    assert "cycle_timeout" in str(last.get("error"))
    assert sched.state()["lifecycle"] == "degraded"
    assert sched.state()["first_tick_ok"] is False
    assert "resolver lifecycle event=timeout" in caplog.text


def test_resolver_timeout_persists_partial_timing_and_abandoned_live(
    monkeypatch, fresh_scheduler
):
    started = threading.Event()
    release = threading.Event()

    monkeypatch.setattr(
        "internal.learning.ledger_heal.heal_daily_pick_ledger",
        lambda dry_run=False: None,
    )

    def _blocked_provider():
        started.set()
        release.wait(timeout=2)
        return []

    monkeypatch.setattr(resolver_scheduler, "RESOLVER_FIRST_TICK_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(resolver_scheduler, "RESOLVER_CYCLE_TIMEOUT_SECONDS", 0.05)
    sched = resolver_scheduler.PredictionResolverScheduler(
        refresh_minutes=1, subnet_provider=_blocked_provider
    )
    sched._active = True
    sched._first_tick_pending = True

    first = sched._run_refresh_cycle_with_timeout()
    assert started.wait(timeout=1)
    assert "cycle_timeout" in str(first["error"])

    with open(weights.SOUL_MAP_PATH, "r") as f:
        soul = json.load(f)
    first_summary = soul["prediction_resolver_scheduler"]["last_cycle"]
    first_timing = first_summary["stage_timing_ms"]
    assert first_summary["active_stage"] == "subnet_provider"
    assert first_summary["abandoned_live"] == 1
    assert first_timing["ledger_heal_ms"] >= 0
    assert first_timing["total_cycle_ms"] >= first_timing["ledger_heal_ms"]

    second = sched._run_refresh_cycle_with_timeout()
    assert second == {"ok": False, "skipped": "previous_cycle_inflight"}
    with open(weights.SOUL_MAP_PATH, "r") as f:
        soul = json.load(f)
    second_summary = soul["prediction_resolver_scheduler"]["last_cycle"]
    assert second_summary["abandoned_live"] == 1

    release.set()


def test_resolver_cycle_timeout_does_not_overlap_inflight_work(
    monkeypatch, fresh_scheduler
):
    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()

    def _blocked(self):
        started.set()
        release.wait(timeout=2)
        finished.set()
        return {
            "ok": True,
            "run_at": resolver_scheduler._now_iso(),
            "resolved_now": 0,
            "expired_now": 0,
            "pending": 0,
        }

    monkeypatch.setattr(resolver_scheduler, "RESOLVER_CYCLE_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(resolver_scheduler, "RESOLVER_FIRST_TICK_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(
        resolver_scheduler.PredictionResolverScheduler,
        "_run_refresh_cycle",
        _blocked,
    )
    sched = resolver_scheduler.PredictionResolverScheduler(
        refresh_minutes=1, subnet_provider=lambda: []
    )
    sched._active = True
    sched._first_tick_pending = True

    timed_out = sched._run_refresh_cycle_with_timeout()
    assert started.wait(timeout=1)
    assert "cycle_timeout" in str(timed_out["error"])

    # Abandoned hung cycle — next tick must not wedge on cycle_in_flight.
    release.set()
    assert finished.wait(timeout=1)
    recovered = sched._run_refresh_cycle_with_timeout()
    deadline = time.time() + 2
    while recovered.get("skipped") == "previous_cycle_inflight" and time.time() < deadline:
        time.sleep(0.01)
        recovered = sched._run_refresh_cycle_with_timeout()
    assert recovered.get("ok") is True
    assert recovered.get("skipped") != "cycle_in_flight"


def test_resolver_worker_rss_end_logged_after_timeout_abandons_cycle(
    caplog, monkeypatch, fresh_scheduler
):
    caplog.set_level(logging.INFO, logger="process_memory")
    monkeypatch.setattr("internal.process_memory.read_rss_kb", lambda pid=None: 1000)
    monkeypatch.setattr("internal.run_mode.get_run_mode", lambda: "worker")
    started = threading.Event()
    release = threading.Event()
    worker_thread_ids: list[int] = []

    def _blocked(self):
        worker_thread_ids.append(threading.get_ident())
        started.set()
        release.wait()
        return {"ok": True, "run_at": resolver_scheduler._now_iso()}

    monkeypatch.setattr(resolver_scheduler, "RESOLVER_CYCLE_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(resolver_scheduler, "RESOLVER_FIRST_TICK_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(
        resolver_scheduler.PredictionResolverScheduler,
        "_run_refresh_cycle",
        _blocked,
    )
    sched = resolver_scheduler.PredictionResolverScheduler(
        refresh_minutes=1, subnet_provider=lambda: []
    )
    sched._active = True
    sched._first_tick_pending = True

    def _worker_lines() -> list[str]:
        # Only this test's worker: an earlier test's abandoned worker can still log here.
        if not worker_thread_ids:
            return []
        return [
            r.getMessage()
            for r in caplog.records
            if "prediction_resolver_worker" in r.getMessage()
            and r.thread == worker_thread_ids[0]
        ]

    try:
        timed_out = sched._run_refresh_cycle_with_timeout()
        assert started.wait(timeout=1)
        assert "cycle_timeout" in str(timed_out["error"])
        assert any("phase=start" in line for line in _worker_lines())
        assert not any("phase=end" in line for line in _worker_lines())
    finally:
        # Unblock the abandoned worker even when an assertion above fails.
        release.set()

    deadline = time.time() + 2
    while time.time() < deadline and not any("phase=end" in line for line in _worker_lines()):
        time.sleep(0.01)
    assert any("phase=end" in line for line in _worker_lines())


def _patchd_payloads(caplog, prefix: str = "patchd_mutation"):
    out = []
    for rec in caplog.records:
        msg = rec.getMessage()
        if not msg.startswith(prefix + " "):
            continue
        out.append(json.loads(msg[len(prefix) + 1 :]))
    return out


def test_patchd_timeout_and_shutdown_call_args_unchanged():
    """Smoke-visible: instrumentation must not change timeout defaults or shutdown args."""
    from pathlib import Path

    sched = Path("internal/council/resolver_scheduler.py").read_text(encoding="utf-8")
    pick = Path("internal/council/pick_scheduler.py").read_text(encoding="utf-8")
    assert 'os.environ.get("RESOLVER_CYCLE_TIMEOUT_SECONDS", "120")' in sched
    assert 'os.environ.get("DAILY_PICK_TICK_TIMEOUT_SECONDS", "90")' in pick
    assert sched.count("pool.shutdown(wait=False, cancel_futures=True)") == 1
    assert pick.count("pool.shutdown(wait=False, cancel_futures=True)") == 1


def test_patchd_mutation_logs_bind_on_executor_thread(
    monkeypatch, fresh_scheduler, tmp_path, caplog
):
    """Worker-thread resolver._save_json logs use the submitted cycle gen, not the parent thread."""
    parent_ident = threading.get_ident()
    worker = {}
    pred_path = tmp_path / "predictions.json"

    def _work(self):
        worker["ident"] = threading.get_ident()
        resolver._save_json(str(pred_path), {"ok": True}, caller="resolver")
        return {
            "ok": True,
            "run_at": resolver_scheduler._now_iso(),
            "resolved_now": 0,
            "expired_now": 0,
            "pending": 0,
        }

    monkeypatch.setattr(
        resolver_scheduler.PredictionResolverScheduler,
        "_run_refresh_cycle",
        _work,
    )
    caplog.set_level(logging.INFO, logger="internal.ops.mutation_log")
    sched = resolver_scheduler.PredictionResolverScheduler(
        refresh_minutes=1, subnet_provider=lambda: []
    )
    sched._active = True
    sched._first_tick_pending = False
    result = sched._run_refresh_cycle_with_timeout()
    assert result.get("ok") is True
    submitted_gen = result["cycle_generation"]
    cycle_id = result["resolver_cycle_id"]
    assert submitted_gen == 1
    parts = str(cycle_id).split(":", 2)
    assert parts[0] == str(os.getpid())
    assert parts[1] == str(submitted_gen)
    assert parts[2]
    assert worker["ident"] != parent_ident
    writes = [
        p
        for p in _patchd_payloads(caplog)
        if p.get("writer_function") == "resolver._save_json"
    ]
    assert writes
    for payload in writes:
        assert payload["cycle_generation"] == submitted_gen
        assert payload["resolver_cycle_id"] == cycle_id
        assert payload["thread_id"] == worker["ident"]
        assert payload["trigger"] == "resolver_save"


def test_patchd_abandoned_worker_keeps_submitted_gen(
    monkeypatch, fresh_scheduler, tmp_path, caplog
):
    """Abandon bumps scheduler gen; orphan worker mutation logs keep submitted gen."""
    started = threading.Event()
    release = threading.Event()
    pred_path = tmp_path / "orphan_predictions.json"

    def _blocked(self):
        started.set()
        release.wait(timeout=2)
        resolver._save_json(str(pred_path), {"orphan": True}, caller="resolver")
        return {
            "ok": True,
            "run_at": resolver_scheduler._now_iso(),
            "resolved_now": 0,
            "expired_now": 0,
            "pending": 0,
        }

    monkeypatch.setattr(resolver_scheduler, "RESOLVER_CYCLE_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(resolver_scheduler, "RESOLVER_FIRST_TICK_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(
        resolver_scheduler.PredictionResolverScheduler,
        "_run_refresh_cycle",
        _blocked,
    )
    caplog.set_level(logging.INFO, logger="internal.ops.mutation_log")
    sched = resolver_scheduler.PredictionResolverScheduler(
        refresh_minutes=1, subnet_provider=lambda: []
    )
    sched._active = True
    sched._first_tick_pending = True
    timed_out = sched._run_refresh_cycle_with_timeout()
    assert started.wait(timeout=1)
    assert "cycle_timeout" in str(timed_out["error"])
    submitted_gen = timed_out["cycle_generation"]
    cycle_id = timed_out["resolver_cycle_id"]
    assert submitted_gen == 1
    assert sched._cycle_generation == submitted_gen + 1
    lifecycle = _patchd_payloads(caplog, prefix="patchd_lifecycle")
    abandon_logs = [p for p in lifecycle if p.get("operation") == "abandon"]
    shutdown_logs = [p for p in lifecycle if p.get("operation") == "shutdown"]
    assert abandon_logs
    assert abandon_logs[-1]["cycle_generation"] == submitted_gen
    assert abandon_logs[-1]["resolver_cycle_id"] == cycle_id
    assert shutdown_logs[-1]["cycle_generation"] == submitted_gen
    assert shutdown_logs[-1]["resolver_cycle_id"] == cycle_id

    release.set()
    writes = []
    deadline = time.time() + 2
    while time.time() < deadline:
        writes = [
            p
            for p in _patchd_payloads(caplog)
            if p.get("writer_function") == "resolver._save_json"
            and p.get("operation") == "skipped_abandoned"
            and p.get("resolver_cycle_id") == cycle_id
        ]
        if writes:
            break
        time.sleep(0.02)
    assert writes
    assert writes[-1]["cycle_generation"] == submitted_gen
    assert writes[-1]["resolver_cycle_id"] == cycle_id
    assert writes[-1]["thread_id"] != threading.get_ident()
    assert not pred_path.exists()


def test_resolver_first_tick_success_is_observable(monkeypatch, fresh_scheduler, caplog):
    caplog.set_level("INFO", logger="internal.council.resolver_scheduler")
    sched = resolver_scheduler.PredictionResolverScheduler(
        refresh_minutes=1, subnet_provider=lambda: [{"netuid": 1, "price": 1.0}]
    )
    sched._active = True
    sched._first_tick_pending = True
    monkeypatch.setattr(
        sched,
        "_run_refresh_cycle_with_timeout",
        lambda: {
            "ok": True,
            "run_at": resolver_scheduler._now_iso(),
            "resolved_now": 0,
            "expired_now": 0,
            "pending": 0,
        },
    )
    monkeypatch.setattr(sched, "_persist_cycle_summary", lambda _result: None)
    monkeypatch.setattr(sched, "_schedule_next", lambda _minutes: None)

    result = sched._tick()

    assert result["ok"] is True
    assert sched.state()["first_tick_ok"] is True
    assert sched.state()["lifecycle"] == "running"
    assert "resolver lifecycle event=success" in caplog.text

# ---------------------------------------------------------------------------
# Tracker persistence isolation (spec §3): trackers must read/write a
# tmp-backed soul map so prior CI runs can never leak into fresh instances.
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def isolate_liveness_persistence(liveness_real_soul_map):
    return liveness_real_soul_map


# ---------------------------------------------------------------------------
# LivenessTracker conformance + honest-skip contract (spec §4)
# ---------------------------------------------------------------------------


def test_resolver_scheduler_liveness_conformance():
    """The scheduler's tracker satisfies every contract check."""
    from liveness_conformance import assert_liveness_compliant

    def factory():
        s = resolver_scheduler.PredictionResolverScheduler(
            refresh_minutes=1, subnet_provider=_static_subnets
        )
        # Persistence is tmp-isolated by autouse fixture, so a fresh
        # tracker genuinely starts with no prior state.
        return s.liveness

    assert_liveness_compliant(factory)


def test_skip_burst_never_produces_ok(monkeypatch, fresh_scheduler):
    """The laundering inversion: repeated heavy-job skips must not read healthy."""
    from contextlib import contextmanager

    @contextmanager
    def _always_busy(_name):
        yield False

    monkeypatch.setattr("internal.heavy_job_gate.heavy_job_slot", _always_busy)
    sched = resolver_scheduler.PredictionResolverScheduler(
        refresh_minutes=1, subnet_provider=lambda: [{"netuid": 1, "price": 1.0}]
    )
    sched._active = True
    for _ in range(3):
        sched._tick()

    snap = sched.liveness.snapshot()
    assert snap["status"] != "ok"
    assert snap["consecutive_skips"] >= 3


# --- Additive observability tests (cycle_history + nonstage_ms); mock-only ---

def test_persist_cycle_summary_maintains_bounded_cycle_history(monkeypatch, fresh_scheduler, tmp_path):
    from internal.council import resolver_scheduler as rs

    soul_path = tmp_path / "soul_map.json"
    soul_path.write_text("{}")
    sched = rs.PredictionResolverScheduler(
        refresh_minutes=1, subnet_provider=_static_subnets, soul_map_path=str(soul_path)
    )

    # Persist 12 fake cycle summaries without running live lock/timeout paths.
    for i in range(12):
        result = {
            "run_at": f"2026-09-06T08:00:{i:02d}Z",
            "ok": True,
            "resolved_now": i,
            "expired_now": 0,
            "pending": 0,
            "error": None,
            "stage_timing_ms": {
                "resolve_due_ms": 10.0 * i,
                "total_cycle_ms": 100.0 + i,
                "stages_sum_ms": 10.0 * i,
                "nonstage_ms": 100.0 + i - 10.0 * i,
            },
            "stages_sum_ms": 10.0 * i,
            "nonstage_ms": 100.0 + i - 10.0 * i,
            "active_stage": None,
            "abandoned_live": 0,
            "batch_size": 0,
        }
        sched._persist_cycle_summary(result)

    import json

    soul = json.loads(soul_path.read_text())
    hist = soul["prediction_resolver_scheduler"]["cycle_history"]
    assert len(hist) <= 10
    assert len(hist) == 10
    assert "cycle_history" in soul["prediction_resolver_scheduler"]
    assert soul["prediction_resolver_scheduler"]["last_cycle"]["run_at"] == hist[-1]["run_at"]
    assert "stages_sum_ms" in hist[-1]
    assert "nonstage_ms" in hist[-1]


def test_cycle_timing_snapshot_exposes_nonstage_ms_keys():
    from internal.council.resolver_scheduler import _CycleTiming

    t = _CycleTiming()
    snap = t.snapshot()
    assert "stages_sum_ms" in snap
    assert "nonstage_ms" in snap

def test_b1_complete_false_on_timeout_partial(monkeypatch, fresh_scheduler):
    """B1 locked decision: an abandoned cycle persists complete=False with start stamp, no end stamp."""
    started = threading.Event()
    release = threading.Event()

    monkeypatch.setattr(
        "internal.learning.ledger_heal.heal_daily_pick_ledger",
        lambda dry_run=False: None,
    )

    def _blocked_provider():
        started.set()
        release.wait(timeout=2)
        return []

    monkeypatch.setattr(resolver_scheduler, "RESOLVER_FIRST_TICK_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(resolver_scheduler, "RESOLVER_CYCLE_TIMEOUT_SECONDS", 0.05)
    sched = resolver_scheduler.PredictionResolverScheduler(
        refresh_minutes=1, subnet_provider=_blocked_provider
    )
    sched._active = True
    sched._first_tick_pending = True

    first = sched._run_refresh_cycle_with_timeout()
    assert started.wait(timeout=1)
    assert "cycle_timeout" in str(first["error"])

    with open(weights.SOUL_MAP_PATH, "r") as f:
        soul = json.load(f)
    summary = soul["prediction_resolver_scheduler"]["last_cycle"]
    stage_timing = summary["stage_timing_ms"]
    gap = summary["gap_timing_ms"]
    assert gap["complete"] is False
    assert isinstance(gap["soul_map_bytes_start"], (int, type(None)))
    assert gap["soul_map_bytes_end"] is None
    # Fence: stage_timing_ms stays numeric-only; gap block is a sibling.
    assert all(isinstance(v, (int, float)) for v in stage_timing.values())
    assert "stages_sum_ms" in summary and "nonstage_ms" in summary

    release.set()


def test_b1_natural_cycle_complete_true_and_inert(monkeypatch, fresh_scheduler):
    """Natural completion: complete=True, stamps present, additive-only diff."""
    monkeypatch.setattr(
        "internal.learning.ledger_heal.heal_daily_pick_ledger",
        lambda dry_run=False: None,
    )
    monkeypatch.setattr(
        resolver,
        "resolve_due_predictions",
        lambda _subnets: {
            "resolved_now": [],
            "expired_now": [],
            "stats": {"pending": 0},
            "watchdog": {},
        },
    )
    monkeypatch.setattr(
        resolver,
        "expire_stale_predictions",
        lambda: {"expired_now": [], "stats": {"pending": 0}, "watchdog": {}},
    )
    monkeypatch.setattr(
        "internal.calibration.scheduler.maybe_trigger_auto_retrain",
        lambda resolved_now: {"triggered": False},
    )

    sched = resolver_scheduler.PredictionResolverScheduler(
        refresh_minutes=1, subnet_provider=lambda: []
    )
    result = sched.run_once()
    assert result["ok"] is True

    with open(weights.SOUL_MAP_PATH, "r") as f:
        soul = json.load(f)
    summary = soul["prediction_resolver_scheduler"]["last_cycle"]
    stage_timing = summary["stage_timing_ms"]
    gap = summary["gap_timing_ms"]
    assert gap["complete"] is True
    assert isinstance(gap["soul_map_bytes_start"], (int, type(None)))
    assert isinstance(gap["soul_map_bytes_end"], (int, type(None)))
    # Inertness: stage_timing_ms stays numeric-only; recorder is a sibling.
    assert all(isinstance(v, (int, float)) for v in stage_timing.values())



# --- B1b: checkpoint buckets t0..t7 + closing-invariant soak ---

_B1B_BUCKET_KEYS = (
    "preflight",
    "ledger_heal_stage",
    "subnet_provider_stage",
    "soul_map_load_stage",
    "batch_bookkeeping",
    "resolve_due_stage",
    "expire_stale_stage",
    "closing",
)


def _b1b_patch_fast_cycle(monkeypatch):
    """Shared fast synthetic cycle stubs (no network)."""
    monkeypatch.setattr(
        "internal.learning.ledger_heal.heal_daily_pick_ledger",
        lambda dry_run=False: None,
    )
    monkeypatch.setattr(
        resolver,
        "resolve_due_predictions",
        lambda _subnets: {
            "resolved_now": [],
            "expired_now": [],
            "stats": {"pending": 0},
            "watchdog": {},
        },
    )
    monkeypatch.setattr(
        resolver,
        "expire_stale_predictions",
        lambda: {"expired_now": [], "stats": {"pending": 0}, "watchdog": {}},
    )
    monkeypatch.setattr(
        "internal.calibration.scheduler.maybe_trigger_auto_retrain",
        lambda resolved_now: {"triggered": False},
    )


def test_b1b_checkpoints_recorded_and_buckets_cover_cycle(monkeypatch, fresh_scheduler):
    """One cycle: t0..t7 monotonic; 8 buckets; invariant/drift within tolerance."""
    _b1b_patch_fast_cycle(monkeypatch)
    sched = resolver_scheduler.PredictionResolverScheduler(
        refresh_minutes=1, subnet_provider=lambda: [{"netuid": 1, "price": 1.0}]
    )
    result = sched.run_once()
    assert result["ok"] is True

    with open(weights.SOUL_MAP_PATH, "r") as f:
        soul = json.load(f)
    summary = soul["prediction_resolver_scheduler"]["last_cycle"]
    gap = summary["gap_timing_ms"]
    stamps = [gap[name] for name in ("t0", "t1", "t2", "t3", "t4", "t5", "t6", "t7")]
    assert all(isinstance(v, (int, float)) for v in stamps)
    assert stamps == sorted(stamps)
    buckets = gap["buckets_ms"]
    assert set(buckets.keys()) == set(_B1B_BUCKET_KEYS)
    stages_sum = float(summary["stages_sum_ms"])
    expected_invariant = round(
        stages_sum
        + float(buckets["preflight"])
        + float(buckets["batch_bookkeeping"])
        + float(buckets["closing"]),
        1,
    )
    assert abs(float(gap["closing_invariant_ms"]) - expected_invariant) <= 0.2
    assert -5.0 <= float(gap["closing_drift_ms"]) <= 5.0
    assert gap["complete"] is True
    assert gap["closing_stamp_ms"] is not None


def test_b1b_stage_timing_numeric_only_fence(monkeypatch, fresh_scheduler):
    """With B1b buckets present, stage_timing_ms values remain int/float only."""
    _b1b_patch_fast_cycle(monkeypatch)
    sched = resolver_scheduler.PredictionResolverScheduler(
        refresh_minutes=1, subnet_provider=lambda: []
    )
    assert sched.run_once()["ok"] is True
    with open(weights.SOUL_MAP_PATH, "r") as f:
        soul = json.load(f)
    summary = soul["prediction_resolver_scheduler"]["last_cycle"]
    stage_timing = summary["stage_timing_ms"]
    assert "gap_timing_ms" not in stage_timing
    assert all(isinstance(v, (int, float)) for v in stage_timing.values())
    assert isinstance(summary["gap_timing_ms"]["buckets_ms"], dict)


def test_b1b_closing_invariant_soak(monkeypatch, fresh_scheduler):
    """25 synthetic cycles: every |closing_drift_ms| <= 5.0; print soak summary."""
    import statistics

    _b1b_patch_fast_cycle(monkeypatch)
    sched = resolver_scheduler.PredictionResolverScheduler(
        refresh_minutes=1, subnet_provider=lambda: [{"netuid": 1, "price": 1.0}]
    )
    drifts = []
    bucket_series = {k: [] for k in _B1B_BUCKET_KEYS}
    for _ in range(25):
        result = sched.run_once()
        assert result["ok"] is True
        with open(weights.SOUL_MAP_PATH, "r") as f:
            soul = json.load(f)
        gap = soul["prediction_resolver_scheduler"]["last_cycle"]["gap_timing_ms"]
        drift = float(gap["closing_drift_ms"])
        assert abs(drift) <= 5.0
        drifts.append(drift)
        for k, v in gap["buckets_ms"].items():
            bucket_series[k].append(float(v))

    def _p90(vals):
        ordered = sorted(vals)
        if not ordered:
            return None
        idx = max(0, int(round(0.9 * (len(ordered) - 1))))
        return ordered[idx]

    print("B1B_SOAK_SUMMARY n=25")
    print(f"drift mean={statistics.mean(drifts):.3f} p90={_p90(drifts):.3f} max={max(drifts):.3f}")
    for k in _B1B_BUCKET_KEYS:
        vals = bucket_series[k]
        print(
            f"bucket {k} mean={statistics.mean(vals):.3f} p90={_p90(vals):.3f} max={max(vals):.3f}"
        )


def test_resolver_restart_seeds_cycle_generation_from_last_cycle(
    tmp_path, monkeypatch
):
    soul = tmp_path / "soul_map.json"
    soul.write_text(
        json.dumps(
            {
                "prediction_resolver_scheduler": {
                    "last_cycle": {
                        "cycle_generation": 47,
                        "run_at": "2020-01-01T00:00:00Z",
                        "ok": True,
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(weights, "SOUL_MAP_PATH", str(soul))
    monkeypatch.setattr(resolver_scheduler, "SOUL_MAP_PATH", str(soul))
    sched = resolver_scheduler.PredictionResolverScheduler(refresh_minutes=15)
    sched._ensure_cycle_generation_seeded()
    assert sched._cycle_generation == 47


def test_resolver_gen2_gen3_interleave_rejects_stale_complete(
    tmp_path, monkeypatch
):
    soul = tmp_path / "soul_map.json"
    soul.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(weights, "SOUL_MAP_PATH", str(soul))
    monkeypatch.setattr(resolver_scheduler, "SOUL_MAP_PATH", str(soul))
    from internal.ops.mutation_log import make_resolver_cycle_id

    sched = resolver_scheduler.PredictionResolverScheduler(refresh_minutes=15)
    run_at = "2026-06-01T12:00:00+00:00"
    id2 = make_resolver_cycle_id(2, run_at)
    id3 = make_resolver_cycle_id(3, run_at)

    def _owned_partial(gen, cycle_id):
        return {
            "run_at": run_at,
            "ok": True,
            "resolved_now": 0,
            "expired_now": 0,
            "pending": 0,
            "cycle_generation": gen,
            "resolver_cycle_id": cycle_id,
            "gap_timing_ms": {"complete": False},
            "stage_timing_ms": {"total_cycle_ms": 1.0},
        }

    sched._persist_owner_gen = 2
    sched._persist_cycle_summary(_owned_partial(2, id2), owner_gen=2)
    sched._persist_owner_gen = 3
    sched._persist_cycle_summary(_owned_partial(3, id3), owner_gen=3)

    stale_complete = _owned_partial(2, id2)
    stale_complete["gap_timing_ms"] = {"complete": True, "closing_drift_ms": 0.0}
    sched._persist_owner_gen = 2
    sched._persist_cycle_summary(stale_complete, owner_gen=2)

    data = json.loads(soul.read_text(encoding="utf-8"))
    last = data["prediction_resolver_scheduler"]["last_cycle"]
    assert last["cycle_generation"] == 3
    assert last["gap_timing_ms"]["complete"] is False


def test_resolver_same_run_at_parsed_equal_z_and_offset():
    z = "2026-01-01T00:00:00Z"
    off = "2026-01-01T00:00:00+00:00"
    assert resolver_scheduler._parse_run_at_utc(z) == resolver_scheduler._parse_run_at_utc(
        off
    )


def test_resolver_natural_run_once_owned_identity_and_terminal_complete(
    monkeypatch, fresh_scheduler
):
    monkeypatch.setattr(
        "internal.learning.ledger_heal.heal_daily_pick_ledger",
        lambda dry_run=False: None,
    )
    monkeypatch.setattr(
        resolver,
        "resolve_due_predictions",
        lambda _subnets: {
            "resolved_now": [],
            "expired_now": [],
            "stats": {"pending": 0},
            "watchdog": {},
        },
    )
    monkeypatch.setattr(
        resolver,
        "expire_stale_predictions",
        lambda: {"expired_now": [], "stats": {"pending": 0}, "watchdog": {}},
    )
    monkeypatch.setattr(
        "internal.calibration.scheduler.maybe_trigger_auto_retrain",
        lambda resolved_now: {"triggered": False},
    )
    sched = resolver_scheduler.PredictionResolverScheduler(
        refresh_minutes=1, subnet_provider=lambda: []
    )
    result = sched.run_once()
    assert result["ok"] is True
    assert result.get("cycle_generation") is not None
    assert result.get("resolver_cycle_id")
    with open(weights.SOUL_MAP_PATH, "r") as f:
        soul = json.load(f)
    summary = soul["prediction_resolver_scheduler"]["last_cycle"]
    assert summary["run_at"] == result["run_at"]
    assert summary["cycle_generation"] == result["cycle_generation"]
    assert summary["resolver_cycle_id"] == result["resolver_cycle_id"]
    assert summary["gap_timing_ms"]["complete"] is True
    assert summary["gap_timing_ms"]["closing_drift_ms"] is not None


# ---------------------------------------------------------------------------
# PR #1571 v5 exam gate (tests 1–17); see docs/resolver-1571-canonical-plan-replit669227-v5.md
# ---------------------------------------------------------------------------


def test_commit_writer_wins_then_revoke(tmp_path, monkeypatch):
    """H1 W1: abandon waits on _release_guard while owned writer holds pre-replace."""
    from internal.ops.mutation_log import make_resolver_cycle_id
    from internal.store import soul_map_io

    soul_path = tmp_path / "soul_map.json"
    soul_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(weights, "SOUL_MAP_PATH", str(soul_path))
    monkeypatch.setattr(resolver_scheduler, "SOUL_MAP_PATH", str(soul_path))

    writer_at_barrier = threading.Event()
    release_writer = threading.Event()
    revoke_entered = threading.Event()
    order: List[str] = []

    def _pre() -> None:
        order.append("W_pre_replace_barrier")
        writer_at_barrier.set()
        assert release_writer.wait(timeout=5)

    monkeypatch.setattr(resolver_scheduler, "_pre_replace_barrier", _pre)

    sched = resolver_scheduler.PredictionResolverScheduler(
        refresh_minutes=1, soul_map_path=str(soul_path), subnet_provider=lambda: []
    )
    gen_at_submit = 5
    rid = make_resolver_cycle_id(gen_at_submit, "2099-01-01T00:00:00+00:00")
    sched._persist_owner_gen = gen_at_submit

    real_abandon = sched._abandon_inflight_cycle

    def _abandon_traced(**kwargs: Any) -> None:
        revoke_entered.set()
        order.append("R_attempt_abandon")
        real_abandon(**kwargs)
        order.append("R_enter_abandon")

    sched._abandon_inflight_cycle = _abandon_traced  # type: ignore[method-assign]

    done_second = threading.Event()

    def _second_write() -> None:
        def _m(blob: Dict[str, Any]) -> None:
            blob["revoke_marker"] = True

        soul_map_io.write_soul_map(_m, str(soul_path), raise_on_lock_timeout=False)
        done_second.set()

    def _writer() -> None:
        sched._persist_cycle_summary(
            {
                "run_at": _iso(datetime.now(timezone.utc)),
                "ok": False,
                "resolved_now": 0,
                "expired_now": 0,
                "pending": 0,
                "error": None,
                "cycle_generation": gen_at_submit,
                "resolver_cycle_id": rid,
                "gap_timing_ms": {"complete": True, "closing_drift_ms": 0.0},
                "stage_timing_ms": {"total_cycle_ms": 1.0},
            },
            owner_gen=gen_at_submit,
        )
        order.append("W_exit")

    def _revoker() -> None:
        assert writer_at_barrier.wait(timeout=5)
        _abandon_traced(submitted_gen=gen_at_submit, resolver_cycle_id=rid)
        order.append("R_exit")

    tw = threading.Thread(target=_writer, name="writer")
    tr = threading.Thread(target=_revoker, name="revoker")
    t2 = threading.Thread(target=_second_write, name="flock_writer")
    tw.start()
    assert writer_at_barrier.wait(timeout=5)
    tr.start()
    t2.start()
    assert revoke_entered.wait(timeout=5)
    time.sleep(0.05)
    assert not done_second.is_set()
    assert "R_enter_abandon" not in order
    release_writer.set()
    tw.join(timeout=10)
    tr.join(timeout=10)
    t2.join(timeout=10)
    assert done_second.is_set()
    assert order.index("W_pre_replace_barrier") < order.index("W_exit")
    assert order.index("W_exit") <= order.index("R_enter_abandon")
    data = json.loads(soul_path.read_text(encoding="utf-8"))
    assert "prediction_resolver_scheduler" in data


def test_revoke_wins_orphan_aborts(tmp_path, monkeypatch):
    """H1 R1: stale owner_gen cannot commit last_cycle."""
    soul = tmp_path / "soul_map.json"
    soul.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(weights, "SOUL_MAP_PATH", str(soul))
    monkeypatch.setattr(resolver_scheduler, "SOUL_MAP_PATH", str(soul))
    from internal.ops.mutation_log import make_resolver_cycle_id

    sched = resolver_scheduler.PredictionResolverScheduler(refresh_minutes=15)
    run_at = "2026-06-01T12:00:00+00:00"
    rid = make_resolver_cycle_id(1, run_at)
    sched._persist_owner_gen = None
    out = sched._persist_cycle_summary(
        {
            "run_at": run_at,
            "ok": True,
            "resolved_now": 0,
            "expired_now": 0,
            "pending": 0,
            "cycle_generation": 1,
            "resolver_cycle_id": rid,
            "gap_timing_ms": {"complete": True},
            "stage_timing_ms": {"total_cycle_ms": 1.0},
        },
        owner_gen=1,
    )
    assert isinstance(out, resolver_scheduler.PersistResult)
    assert out.committed is False
    before = hashlib.sha256(soul.read_bytes()).hexdigest()
    after = hashlib.sha256(soul.read_bytes()).hexdigest()
    assert before == after
    data = json.loads(soul.read_text(encoding="utf-8"))
    assert "last_cycle" not in data.get("prediction_resolver_scheduler", {})


def test_persist_rejects_owned_write_after_abandon_between_entry_and_mutator(
    tmp_path, monkeypatch
):
    """persist-1724: entry passed with valid gen; abandon clears gen before mutator."""
    soul = tmp_path / "soul_map.json"
    soul.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(weights, "SOUL_MAP_PATH", str(soul))
    monkeypatch.setattr(resolver_scheduler, "SOUL_MAP_PATH", str(soul))
    from internal.ops.mutation_log import make_resolver_cycle_id
    from internal.store import soul_map_io

    sched = resolver_scheduler.PredictionResolverScheduler(refresh_minutes=15)
    rid = make_resolver_cycle_id(3, "2026-06-01T13:00:00+00:00")
    sched._persist_owner_gen = 3
    real_write = soul_map_io.write_soul_map

    def _write_clear_gen_then_mutate(mutator, path, **kwargs):
        sched._persist_owner_gen = None
        return real_write(mutator, path, **kwargs)

    monkeypatch.setattr(
        resolver_scheduler, "write_soul_map", _write_clear_gen_then_mutate
    )
    out = sched._persist_cycle_summary(
        {
            "run_at": "2026-06-01T13:00:00+00:00",
            "ok": True,
            "resolved_now": 0,
            "expired_now": 0,
            "pending": 0,
            "cycle_generation": 3,
            "resolver_cycle_id": rid,
            "gap_timing_ms": {"complete": True},
            "stage_timing_ms": {"total_cycle_ms": 1.0},
        },
        owner_gen=3,
    )
    assert isinstance(out, resolver_scheduler.PersistResult)
    data = json.loads(soul.read_text(encoding="utf-8"))
    prs = data.get("prediction_resolver_scheduler", {})
    assert "last_cycle" not in prs


def test_persist_rejects_owned_write_when_owner_revoked(tmp_path, monkeypatch):
    """CR-05: non-force owned persist fails when _persist_owner_gen was revoked."""
    soul = tmp_path / "soul_map.json"
    soul.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(weights, "SOUL_MAP_PATH", str(soul))
    monkeypatch.setattr(resolver_scheduler, "SOUL_MAP_PATH", str(soul))
    from internal.ops.mutation_log import make_resolver_cycle_id

    sched = resolver_scheduler.PredictionResolverScheduler(refresh_minutes=15)
    rid = make_resolver_cycle_id(2, "2026-06-01T12:00:00+00:00")
    sched._persist_owner_gen = None
    out = sched._persist_cycle_summary(
        {
            "run_at": "2026-06-01T12:00:00+00:00",
            "ok": True,
            "resolved_now": 0,
            "expired_now": 0,
            "pending": 0,
            "cycle_generation": 2,
            "resolver_cycle_id": rid,
            "gap_timing_ms": {"complete": True},
            "stage_timing_ms": {"total_cycle_ms": 1.0},
        },
        owner_gen=2,
    )
    assert out.committed is False


def test_tick_when_inactive_is_stale_scheduler_run(fresh_scheduler):
    """CR-04: stopped scheduler ignores scheduled tick callbacks with expected run id."""
    sched = resolver_scheduler.PredictionResolverScheduler(refresh_minutes=1)
    rid = resolver_scheduler.SchedulerRunId("run-a")
    sched._tick_run_id = rid
    sched._active = True
    sched.stop()
    out = sched._tick(rid)
    assert out.get("skipped") == "stale_scheduler_run"


def test_stop_compare_clear_preserves_replaced_tick_run_id(tmp_path, monkeypatch):
    """Ditto P3-R1: persist yield must not clear a newer _tick_run_id."""
    soul_path = tmp_path / "soul_map.json"
    soul_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(weights, "SOUL_MAP_PATH", str(soul_path))
    monkeypatch.setattr(resolver_scheduler, "SOUL_MAP_PATH", str(soul_path))
    sched = resolver_scheduler.PredictionResolverScheduler(
        refresh_minutes=1, soul_map_path=str(soul_path)
    )
    sched.start(immediate=False)
    armed = sched._tick_run_id
    assert armed is not None
    replacement = resolver_scheduler.SchedulerRunId("replaced-during-persist")
    real_pls = sched._persist_lifecycle_state

    def _persist_then_replace(**kwargs):
        sched._tick_run_id = replacement
        return real_pls(**kwargs)

    monkeypatch.setattr(
        sched, "_persist_lifecycle_state", _persist_then_replace
    )
    sched.stop()
    assert sched._tick_run_id is replacement
    out = sched._tick(armed)
    assert out.get("skipped") == "stale_scheduler_run"


def test_stop_clears_tick_run_id_so_armed_callback_is_stale(fresh_scheduler):
    """Cluster 4: stop invalidates scheduler_run_id, not only _active."""
    sched = resolver_scheduler.PredictionResolverScheduler(refresh_minutes=1)
    sched.start(immediate=False)
    armed = sched._tick_run_id
    assert armed is not None
    sched.stop()
    assert sched._tick_run_id is None
    out = sched._tick(armed)
    assert out.get("skipped") == "stale_scheduler_run"


def test_tick_without_run_id_when_inactive_is_stale_scheduler_run(fresh_scheduler):
    """CR-04: request-triggered _tick() on a stopped scheduler is a no-op."""
    sched = resolver_scheduler.PredictionResolverScheduler(refresh_minutes=1)
    sched.start(immediate=False)
    sched.stop()
    out = sched._tick()
    assert out.get("skipped") == "stale_scheduler_run"


def test_zero_budget_cycle_bumps_generation_before_owner_publish(
    monkeypatch, fresh_scheduler
):
    """Revive/zero-budget path must open a generation it can publish as owner."""
    monkeypatch.setattr(resolver_scheduler, "RESOLVER_FIRST_TICK_TIMEOUT_SECONDS", 0)
    sched = resolver_scheduler.PredictionResolverScheduler(refresh_minutes=1)
    gen_before = sched._cycle_generation

    def _quick_cycle(self):
        return {"ok": True, "resolved_now": 0, "expired_now": 0, "pending": 0}

    monkeypatch.setattr(
        resolver_scheduler.PredictionResolverScheduler,
        "_run_refresh_cycle",
        _quick_cycle,
    )
    sched._active = True
    sched._first_tick_pending = True
    sched._revive_use_full_budget = False
    out = sched._run_refresh_cycle_with_timeout()
    assert out.get("ok") is True
    assert sched._cycle_generation == gen_before + 1
    assert out.get("cycle_generation") == gen_before + 1


def test_immediate_start_captures_run_id_for_first_tick(monkeypatch, fresh_scheduler):
    """CR-01: immediate thread uses run id captured at start, not later mutation."""
    sched = resolver_scheduler.PredictionResolverScheduler(refresh_minutes=1)
    seen: Dict[str, Any] = {}

    def _fake_tick(self, expected_run_id=None, **_k):
        seen["rid"] = expected_run_id.value if expected_run_id else None
        return {"ok": True}

    monkeypatch.setattr(
        resolver_scheduler.PredictionResolverScheduler, "_tick", _fake_tick
    )
    sched.start(immediate=True)
    assert seen.get("rid") is not None
    captured = sched._tick_run_id
    time.sleep(0.15)
    sched.stop()
    time.sleep(0.15)
    assert captured is not None
    assert seen.get("rid") == captured.value
    assert sched._tick_run_id is None


def test_gate_deadline_returns_pending(monkeypatch, tmp_path):
    """M2: flock deadline exhaustion yields non-commit from write_soul_map."""
    from internal.store import soul_map_io

    soul_path = tmp_path / "soul_map.json"
    seed = b'{"seed": true}'
    soul_path.write_bytes(seed)

    def _instant_timeout(*_a, **_k):
        raise TimeoutError("Timed out waiting for flock test")

    monkeypatch.setattr(soul_map_io, "_acquire_write_locks", _instant_timeout)
    result = soul_map_io.write_soul_map(
        lambda b: b.update({"x": 1}),
        path=str(soul_path),
        raise_on_lock_timeout=False,
    )
    from internal.store.soul_map_io import WriteOutcome

    assert result.outcome is WriteOutcome.LOCK_WAIT_FAILED
    assert result.blob is None
    assert soul_path.read_bytes() == seed


def test_revive_does_not_block_state_read(monkeypatch, fresh_scheduler):
    """H2: module get_state does not hold _scheduler_lock across instance state()."""
    hold = threading.Event()
    release = threading.Event()

    real_state = resolver_scheduler.PredictionResolverScheduler.state

    def _slow_state(self):
        hold.set()
        assert release.wait(timeout=5)
        return real_state(self)

    monkeypatch.setattr(
        resolver_scheduler.PredictionResolverScheduler, "state", _slow_state
    )
    resolver_scheduler.start_prediction_resolver_scheduler(immediate=True)
    time.sleep(0.2)

    def _read() -> None:
        resolver_scheduler.get_prediction_resolver_scheduler_state()

    t1 = threading.Thread(target=_read)
    t2 = threading.Thread(target=_read)
    t1.start()
    assert hold.wait(timeout=5)
    t2.start()
    time.sleep(0.05)
    assert t1.is_alive()
    assert t2.is_alive()
    release.set()
    t1.join(timeout=5)
    t2.join(timeout=5)
    resolver_scheduler.stop_prediction_resolver_scheduler()


def test_state_read_not_blocked_by_lifecycle_io(tmp_path, monkeypatch):
    """H2: health read returns while lifecycle write is stalled."""
    soul_path = tmp_path / "soul_map.json"
    soul_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(weights, "SOUL_MAP_PATH", str(soul_path))
    monkeypatch.setattr(resolver_scheduler, "SOUL_MAP_PATH", str(soul_path))

    from internal.store import soul_map_io

    started = threading.Event()
    resume = threading.Event()

    # Scheduler calls the name bound in resolver_scheduler, not soul_map_io.write_soul_map.
    real_write = resolver_scheduler.write_soul_map
    stall_target = str(Path(soul_path).resolve())

    def _stall_write(mutator, path=None, **kwargs):
        resolved = (
            str(Path(path).resolve())
            if path is not None
            else str(Path(soul_map_io._resolve_path(None)).resolve())
        )
        if resolved == stall_target:
            started.set()
            assert resume.wait(timeout=5)
        return real_write(mutator, path=path, **kwargs)

    monkeypatch.setattr(resolver_scheduler, "write_soul_map", _stall_write)

    sched = resolver_scheduler.PredictionResolverScheduler(
        refresh_minutes=1, soul_map_path=str(soul_path)
    )
    sched._active = True
    sched._lifecycle = "running"
    sched._started_at = _iso(datetime.now(timezone.utc))

    def _io() -> None:
        sched._persist_lifecycle_state()

    t = threading.Thread(target=_io)
    t.start()
    assert started.wait(timeout=5)
    t0 = time.perf_counter()
    resolver_scheduler.get_prediction_resolver_scheduler_state()
    dt = time.perf_counter() - t0
    assert dt < 0.25
    resume.set()
    t.join(timeout=5)


def test_late_old_stop_cannot_cancel_new_job(monkeypatch, fresh_scheduler):
    """H4: stop cancels only the stopped instance job ids."""
    calls: List[str] = []

    class _FakeSched:
        def remove_job(self, jid: str) -> None:
            calls.append(f"cancel:{jid}")

    def _sched(jid: str, *_a, **_k) -> None:
        calls.append(f"schedule:{jid}")

    monkeypatch.setattr(
        "internal.job_scheduler.get_background_scheduler", lambda: _FakeSched()
    )
    monkeypatch.setattr(resolver_scheduler, "schedule_in_seconds", _sched)

    s1 = resolver_scheduler.PredictionResolverScheduler(refresh_minutes=1)
    s1.start(immediate=False)
    jid1 = s1._job_primary()
    out1 = s1.stop()
    assert out1.get("stopped") is True
    assert out1.get("lifecycle_persisted") is True
    assert f"schedule:{jid1}" in calls
    assert f"cancel:{jid1}" in calls
    assert f"cancel:{jid1}:retry" in calls

    calls.clear()
    s2 = resolver_scheduler.PredictionResolverScheduler(refresh_minutes=1)
    s2.start(immediate=False)
    jid2 = s2._job_primary()
    assert jid1 != jid2
    _FakeSched().remove_job(jid1)
    cancel_targets = [c.removeprefix("cancel:") for c in calls if c.startswith("cancel:")]
    assert jid2 not in cancel_targets
    assert f"{jid2}:retry" not in cancel_targets


def test_detached_lifecycle_write_is_fenced(monkeypatch, fresh_scheduler):
    """H3 TOCTOU: skip cycle_in_flight appends history without replacing last_cycle."""
    soul_path = weights.SOUL_MAP_PATH
    sched = resolver_scheduler.PredictionResolverScheduler(
        refresh_minutes=1, soul_map_path=str(soul_path)
    )
    sched._persist_cycle_summary(
        {"run_at": "2020-01-01T00:00:00Z", "ok": True, "skipped": "cycle_in_flight"}
    )
    with open(soul_path, "r") as f:
        data = json.load(f)
    prs = data["prediction_resolver_scheduler"]
    # cycle_in_flight is history-only (does not replace last_cycle).
    lc = prs.get("last_cycle")
    if isinstance(lc, dict):
        assert lc.get("skipped") != "cycle_in_flight"
    hist = prs["cycle_history"]
    assert any(h.get("skipped") == "cycle_in_flight" for h in hist)


def test_singleton_detach_lifecycle_write_is_fenced(tmp_path, monkeypatch):
    """H3 detached: stale stop lifecycle cannot clobber a newer scheduler_run_id."""
    soul_path = tmp_path / "soul_map.json"
    soul_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(weights, "SOUL_MAP_PATH", str(soul_path))
    monkeypatch.setattr(resolver_scheduler, "SOUL_MAP_PATH", str(soul_path))

    hold = threading.Event()
    release = threading.Event()

    old = resolver_scheduler.PredictionResolverScheduler(
        refresh_minutes=1, soul_map_path=str(soul_path)
    )
    old.start(immediate=False)
    old_run = old._tick_run_id.value if old._tick_run_id else None
    real_pls = old._persist_lifecycle_state

    def _slow_pls(*_a, **_k) -> resolver_scheduler.PersistResult:
        hold.set()
        assert release.wait(timeout=5)
        return real_pls(*_a, **_k)

    old._persist_lifecycle_state = _slow_pls  # type: ignore[method-assign]

    t_stop = threading.Thread(target=old.stop)
    t_stop.start()
    assert hold.wait(timeout=5)

    new = resolver_scheduler.PredictionResolverScheduler(
        refresh_minutes=1, soul_map_path=str(soul_path)
    )
    new.start(immediate=False)
    new_run = new._tick_run_id.value
    assert new_run != old_run
    mid = json.loads(soul_path.read_text(encoding="utf-8"))
    assert mid["prediction_resolver_scheduler"]["scheduler_run_id"] == new_run

    release.set()
    t_stop.join(timeout=10)

    data = json.loads(soul_path.read_text(encoding="utf-8"))
    prs = data["prediction_resolver_scheduler"]
    assert prs.get("scheduler_run_id") == new_run
    assert prs.get("lifecycle") not in ("stopped",)


def test_cycle_ab_overlap_valid_b_persists_b_identity(monkeypatch, fresh_scheduler):
    """H3 valid B: ContextVar carries B identity in worker thread."""
    from internal.ops.mutation_log import make_resolver_cycle_id

    sched = resolver_scheduler.PredictionResolverScheduler(refresh_minutes=1)
    b = threading.Barrier(2)
    rid_b = make_resolver_cycle_id(2, "2026-01-02T00:00:00Z")
    ctx_b = resolver_scheduler._CycleContext(
        run_at="2026-01-02T00:00:00Z",
        cycle_generation=2,
        resolver_cycle_id=rid_b,
    )
    seen: Dict[str, Any] = {}

    def _worker() -> None:
        tok = resolver_scheduler._active_cycle_ctx_var.set(ctx_b)
        try:
            b.wait()
            c = resolver_scheduler._active_cycle_ctx_var.get()
            seen["ctx"] = c
        finally:
            resolver_scheduler._active_cycle_ctx_var.reset(tok)

    pool = __import__("concurrent.futures", fromlist=["ThreadPoolExecutor"]).ThreadPoolExecutor(
        max_workers=1
    )
    fut = pool.submit(_worker)
    b.wait()
    fut.result(timeout=5)
    assert seen["ctx"].resolver_cycle_id == rid_b
    pool.shutdown(wait=False)


def test_cycle_ab_overlap_persists_b_identity_on_disk(tmp_path, monkeypatch):
    """GAP-08: durable last_cycle carries resolver_cycle_id for owned persist."""
    from internal.ops.mutation_log import make_resolver_cycle_id

    soul = tmp_path / "soul_map.json"
    soul.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(weights, "SOUL_MAP_PATH", str(soul))
    monkeypatch.setattr(resolver_scheduler, "SOUL_MAP_PATH", str(soul))
    sched = resolver_scheduler.PredictionResolverScheduler(refresh_minutes=1)
    run_at = "2026-01-02T00:00:00+00:00"
    rid_b = make_resolver_cycle_id(2, run_at)
    sched._persist_owner_gen = 2
    sched._persist_cycle_summary(
        {
            "run_at": run_at,
            "ok": True,
            "resolved_now": 1,
            "expired_now": 0,
            "pending": 0,
            "cycle_generation": 2,
            "resolver_cycle_id": rid_b,
            "gap_timing_ms": {"complete": True, "closing_drift_ms": 0.0},
            "stage_timing_ms": {"total_cycle_ms": 1.0},
        },
        owner_gen=2,
    )
    data = json.loads(soul.read_text(encoding="utf-8"))
    last = data["prediction_resolver_scheduler"]["last_cycle"]
    assert last["resolver_cycle_id"] == rid_b
    assert last["cycle_generation"] == 2


def test_cycle_context_rejected_when_lease_revoked(monkeypatch, fresh_scheduler):
    """H3 stale: generation mismatch in worker returns cycle_abandoned."""
    sched = resolver_scheduler.PredictionResolverScheduler(refresh_minutes=1)

    class _FakeFut:
        def __init__(self, fn: Any) -> None:
            self._fn = fn

        def done(self) -> bool:
            return False

        def result(self, *_a, **_k) -> Any:
            sched._cycle_generation += 100
            return self._fn()

    class _FakePool:
        def __init__(self, *a: Any, **k: Any) -> None:
            pass

        def submit(self, fn: Any) -> _FakeFut:
            return _FakeFut(fn)

        def shutdown(self, *a: Any, **k: Any) -> None:
            pass

    monkeypatch.setattr(resolver_scheduler, "ThreadPoolExecutor", _FakePool)
    monkeypatch.setattr(sched, "_cycle_lock", threading.Lock())
    monkeypatch.setattr(resolver_scheduler, "RESOLVER_FIRST_TICK_TIMEOUT_SECONDS", 120)
    monkeypatch.setattr(resolver_scheduler, "RESOLVER_CYCLE_TIMEOUT_SECONDS", 120)
    out = sched._run_refresh_cycle_with_timeout()
    assert out.get("skipped") == "cycle_abandoned"


def test_force_timeout_before_first_partial_replaces_older_incomplete(
    tmp_path, monkeypatch
):
    """H5: force timeout path may replace incomplete same id (existing behavior)."""
    soul = tmp_path / "soul_map.json"
    soul.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(weights, "SOUL_MAP_PATH", str(soul))
    monkeypatch.setattr(resolver_scheduler, "SOUL_MAP_PATH", str(soul))
    from internal.ops.mutation_log import make_resolver_cycle_id

    sched = resolver_scheduler.PredictionResolverScheduler(refresh_minutes=15)
    run_at = "2026-08-01T00:00:00+00:00"
    rid = make_resolver_cycle_id(3, run_at)
    partial = {
        "run_at": run_at,
        "ok": False,
        "resolved_now": 0,
        "expired_now": 0,
        "pending": 0,
        "cycle_generation": 3,
        "resolver_cycle_id": rid,
        "gap_timing_ms": {"complete": False},
        "stage_timing_ms": {"total_cycle_ms": 1.0},
        "error": "cycle_timeout_1s",
    }
    sched._persist_owner_gen = 3
    sched._persist_cycle_summary(partial, owner_gen=3, force=True)
    data = json.loads(soul.read_text(encoding="utf-8"))
    assert data["prediction_resolver_scheduler"]["last_cycle"]["error"] == "cycle_timeout_1s"


def test_force_timeout_newer_generation_replaces_older_incomplete(
    tmp_path, monkeypatch
):
    """H5: authorized force timeout (gen 8) replaces older incomplete gen 7 row."""
    soul = tmp_path / "soul_map.json"
    soul.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(weights, "SOUL_MAP_PATH", str(soul))
    monkeypatch.setattr(resolver_scheduler, "SOUL_MAP_PATH", str(soul))
    from internal.ops.mutation_log import make_resolver_cycle_id

    sched = resolver_scheduler.PredictionResolverScheduler(refresh_minutes=15)
    run7 = "2026-08-01T00:00:00+00:00"
    run8 = "2026-08-02T00:00:00+00:00"
    rid7 = make_resolver_cycle_id(7, run7)
    rid8 = make_resolver_cycle_id(8, run8)
    gen7 = {
        "run_at": run7,
        "ok": False,
        "resolved_now": 0,
        "expired_now": 0,
        "pending": 0,
        "cycle_generation": 7,
        "resolver_cycle_id": rid7,
        "gap_timing_ms": {"complete": False},
        "stage_timing_ms": {"total_cycle_ms": 1.0},
        "error": "cycle_timeout_1s",
    }
    sched._persist_owner_gen = 7
    sched._persist_cycle_summary(gen7, owner_gen=7, force=True)
    sched._persist_owner_gen = 8
    gen8 = {
        "run_at": run8,
        "ok": False,
        "resolved_now": 0,
        "expired_now": 0,
        "pending": 0,
        "cycle_generation": 8,
        "resolver_cycle_id": rid8,
        "gap_timing_ms": {"complete": False},
        "stage_timing_ms": {"total_cycle_ms": 1.0},
        "error": "cycle_timeout_2s",
    }
    sched._persist_cycle_summary(gen8, owner_gen=8, force=True)
    data = json.loads(soul.read_text(encoding="utf-8"))
    last = data["prediction_resolver_scheduler"]["last_cycle"]
    assert last["cycle_generation"] == 8
    assert last["resolver_cycle_id"] == rid8
    assert last["error"] == "cycle_timeout_2s"


def test_completed_success_beats_parses_persisted_existing_generation():
    """Ditto P2: persisted existing row (string gen) must compare, not mis-read as None."""
    existing = {
        "run_at": "2026-08-01T00:00:00+00:00",
        "ok": True,
        "cycle_generation": "5",
        "gap_timing_ms": {"complete": True},
    }
    incoming = {
        "run_at": "2026-08-01T01:00:00+00:00",
        "ok": True,
        "cycle_generation": 6,
        "gap_timing_ms": {"complete": True},
    }
    assert resolver_scheduler._completed_success_beats(existing, incoming) is True
    assert resolver_scheduler._completed_success_beats(incoming, existing) is False


def test_last_cycle_equal_gen_newer_run_at_completed_success_wins(tmp_path, monkeypatch):
    """Policy falsifier A: same generation, later run_at — newer success wins last_cycle."""
    from internal.ops.mutation_log import make_resolver_cycle_id

    soul = tmp_path / "soul_map.json"
    soul.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(weights, "SOUL_MAP_PATH", str(soul))
    monkeypatch.setattr(resolver_scheduler, "SOUL_MAP_PATH", str(soul))
    sched = resolver_scheduler.PredictionResolverScheduler(refresh_minutes=15)
    gen = 5
    run0 = "2026-08-01T00:00:00+00:00"
    run1 = "2026-08-01T01:00:00+00:00"
    rid_a = make_resolver_cycle_id(gen, run0)
    rid_b = make_resolver_cycle_id(gen, run1)
    first = {
        "run_at": run0,
        "ok": True,
        "resolved_now": 1,
        "expired_now": 0,
        "pending": 0,
        "cycle_generation": gen,
        "resolver_cycle_id": rid_a,
        "gap_timing_ms": {"complete": True, "closing_drift_ms": 0.1},
        "stage_timing_ms": {"total_cycle_ms": 1.0},
    }
    sched._persist_owner_gen = gen
    sched._persist_cycle_summary(first, owner_gen=gen)
    second = {
        "run_at": run1,
        "ok": True,
        "resolved_now": 2,
        "expired_now": 0,
        "pending": 0,
        "cycle_generation": gen,
        "resolver_cycle_id": rid_b,
        "gap_timing_ms": {"complete": True, "closing_drift_ms": 0.2},
        "stage_timing_ms": {"total_cycle_ms": 2.0},
    }
    sched._persist_cycle_summary(second, owner_gen=gen)
    data = json.loads(soul.read_text(encoding="utf-8"))
    last = data["prediction_resolver_scheduler"]["last_cycle"]
    assert last["resolver_cycle_id"] == rid_b
    assert last["run_at"] == run1


def test_last_cycle_failure_appends_history_not_replace_success(tmp_path, monkeypatch):
    """Policy falsifier B: failure after completed success — history only on last_cycle."""
    from internal.ops.mutation_log import make_resolver_cycle_id

    soul = tmp_path / "soul_map.json"
    soul.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(weights, "SOUL_MAP_PATH", str(soul))
    monkeypatch.setattr(resolver_scheduler, "SOUL_MAP_PATH", str(soul))
    sched = resolver_scheduler.PredictionResolverScheduler(refresh_minutes=15)
    run_at = "2026-08-01T00:00:00+00:00"
    rid_ok = make_resolver_cycle_id(4, run_at)
    rid_fail = make_resolver_cycle_id(5, "2026-08-02T00:00:00+00:00")
    success = {
        "run_at": run_at,
        "ok": True,
        "resolved_now": 1,
        "expired_now": 0,
        "pending": 0,
        "cycle_generation": 4,
        "resolver_cycle_id": rid_ok,
        "gap_timing_ms": {"complete": True, "closing_drift_ms": 0.1},
        "stage_timing_ms": {"total_cycle_ms": 10.0},
    }
    sched._persist_owner_gen = 4
    sched._persist_cycle_summary(success, owner_gen=4)
    sched._persist_owner_gen = 5
    failure = {
        "run_at": "2026-08-02T00:00:00+00:00",
        "ok": False,
        "resolved_now": 0,
        "expired_now": 0,
        "pending": 0,
        "cycle_generation": 5,
        "resolver_cycle_id": rid_fail,
        "gap_timing_ms": {"complete": False},
        "stage_timing_ms": {"total_cycle_ms": 1.0},
        "error": "cycle_timeout_1s",
    }
    sched._persist_cycle_summary(failure, owner_gen=5, force=True)
    data = json.loads(soul.read_text(encoding="utf-8"))
    sched_blob = data["prediction_resolver_scheduler"]
    last = sched_blob["last_cycle"]
    history = sched_blob.get("cycle_history") or []
    assert last["resolver_cycle_id"] == rid_ok
    assert last["cycle_generation"] == 4
    assert any(row.get("error") == "cycle_timeout_1s" for row in history)


def test_force_timeout_preserves_completed_success_and_newer_generation(
    tmp_path, monkeypatch
):
    """H5: completed success is not clobbered by stale force."""
    soul = tmp_path / "soul_map.json"
    soul.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(weights, "SOUL_MAP_PATH", str(soul))
    monkeypatch.setattr(resolver_scheduler, "SOUL_MAP_PATH", str(soul))
    from internal.ops.mutation_log import make_resolver_cycle_id

    sched = resolver_scheduler.PredictionResolverScheduler(refresh_minutes=15)
    run_at = "2026-08-01T00:00:00+00:00"
    rid4 = make_resolver_cycle_id(4, run_at)
    rid3 = make_resolver_cycle_id(3, run_at)
    success = {
        "run_at": run_at,
        "ok": True,
        "resolved_now": 1,
        "expired_now": 0,
        "pending": 0,
        "cycle_generation": 4,
        "resolver_cycle_id": rid4,
        "gap_timing_ms": {"complete": True, "closing_drift_ms": 0.1},
        "stage_timing_ms": {"total_cycle_ms": 10.0},
    }
    sched._persist_owner_gen = 4
    sched._persist_cycle_summary(success, owner_gen=4)
    sched._persist_owner_gen = 3
    stale = {
        "run_at": run_at,
        "ok": False,
        "resolved_now": 0,
        "expired_now": 0,
        "pending": 0,
        "cycle_generation": 3,
        "resolver_cycle_id": rid3,
        "gap_timing_ms": {"complete": False},
        "stage_timing_ms": {"total_cycle_ms": 1.0},
    }
    sched._persist_cycle_summary(stale, owner_gen=3, force=True)
    data = json.loads(soul.read_text(encoding="utf-8"))
    last = data["prediction_resolver_scheduler"]["last_cycle"]
    assert last["cycle_generation"] == 4
    assert last["resolver_cycle_id"] == rid4


def test_persist_cycle_summary_typed_non_commit_on_boundary(tmp_path, monkeypatch):
    """M1: soul_map write failure surfaces as committed=False."""
    from internal.store import soul_map_io

    soul_path = tmp_path / "soul_map.json"
    seed = b'{"stable": true}'
    soul_path.write_bytes(seed)
    monkeypatch.setattr(weights, "SOUL_MAP_PATH", str(soul_path))
    monkeypatch.setattr(resolver_scheduler, "SOUL_MAP_PATH", str(soul_path))

    def _boom(*_a, **_k):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", _boom)
    sched = resolver_scheduler.PredictionResolverScheduler(
        refresh_minutes=1, soul_map_path=str(soul_path)
    )
    pr = sched._persist_cycle_summary(
        {"run_at": _iso(datetime.now(timezone.utc)), "ok": False, "resolved_now": 0, "expired_now": 0, "pending": 0}
    )
    assert isinstance(pr, resolver_scheduler.PersistResult)
    assert pr.committed is False
    assert soul_path.read_bytes() == seed


def test_stop_revive_typed_transition_on_abort(monkeypatch, fresh_scheduler):
    """M1: stop returns typed stopped dict and lifecycle_persisted (singleton path)."""
    resolver_scheduler.start_prediction_resolver_scheduler(immediate=False)
    out = resolver_scheduler.stop_prediction_resolver_scheduler()
    assert out.get("stopped") is True
    assert out.get("lifecycle_persisted") is True
    assert "pending" not in out


def test_r2_partial_completion_and_stamp_enrichment(tmp_path, monkeypatch):
    """M3 R2: alias — partial then complete same id (Track B)."""
    test_resolver_gen2_gen3_interleave_rejects_stale_complete(tmp_path, monkeypatch)


def test_r2_timeout_cannot_replace_completed_success(tmp_path, monkeypatch):
    """M3 R2: completed success preserved vs lower gen force (overlap with H5)."""
    test_force_timeout_preserves_completed_success_and_newer_generation(tmp_path, monkeypatch)


def test_r3_stale_skip_is_history_only(monkeypatch, fresh_scheduler):
    """M3 R3 stale: cycle_in_flight stays history-only."""
    test_detached_lifecycle_write_is_fenced(monkeypatch, fresh_scheduler)


def test_r3_fresh_heavy_job_skip_is_recorded(monkeypatch, fresh_scheduler):
    """M3 R3 fresh: heavy_job_busy skip is observable in last_cycle."""
    test_scheduler_skip_persists_last_cycle_when_heavy_job_busy(monkeypatch, fresh_scheduler)
