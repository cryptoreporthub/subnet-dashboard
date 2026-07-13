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

import json
import os
from datetime import datetime, timedelta, timezone
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


@pytest.fixture
def nudge_spy(monkeypatch):
    """Capture weight nudges without touching the filesystem."""
    calls: List[Any] = []

    def _fake_nudge(correct, expert):
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


def test_scheduler_run_once_resolves_due_predictions(nudge_spy, fresh_scheduler):
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


def test_scheduler_passes_batch_not_full_list(monkeypatch, fresh_scheduler):
    subnets = [{"netuid": i, "price": float(i)} for i in range(1, 51)]
    seen = {}

    def _spy_resolve(batch):
        seen["batch_len"] = len(batch)
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

    assert seen["batch_len"] == 8
