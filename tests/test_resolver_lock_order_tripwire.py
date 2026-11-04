"""Learning writes that run under a cycle's release guard must not take the scheduler locks.

The revive path holds ``_scheduler_lock`` and then waits on ``sched._release_guard``.
A write that holds the guard and then takes ``_scheduler_lock`` or ``sched._submit_lock``
would close that cycle and deadlock the health path.

The pass below holds the guard across a full, unstubbed resolver run. That is the
strictest placement a per-site guard could use, so a violation here is a violation
for any narrower placement too.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

import pytest

import internal.council.expert_attribution as expert_attribution
import internal.council.pick_history as pick_history
import internal.council.prediction_trace as prediction_trace
import internal.council.resolver as resolver
import internal.council.resolver_scheduler as resolver_scheduler
import internal.council.scenario_memory as scenario_memory
import internal.council.signal_expert as signal_expert
import internal.council.weights as weights
import internal.learning.evidence as evidence
import internal.learning.trail_events as trail_events


NETUID = 7
PASS_TIMEOUT_SECONDS = 30


class _OrderTripwire:
    """Lock wrapper that records each acquire made while this scheduler's release guard is held."""

    def __init__(self, name: str, inner: Any, sched: Any, violations: List[str]) -> None:
        self._name = name
        self._inner = inner
        self._sched = sched
        self._violations = violations

    def acquire(self, blocking: bool = True, timeout: float = -1) -> bool:
        if self._sched._release_guard._is_owned():
            self._violations.append(self._name)
        return self._inner.acquire(blocking, timeout)

    def release(self) -> None:
        self._inner.release()

    def locked(self) -> bool:
        return self._inner.locked()

    def __enter__(self) -> "_OrderTripwire":
        self.acquire()
        return self

    def __exit__(self, *_exc: Any) -> bool:
        self.release()
        return False


@pytest.fixture
def pass_env(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.chdir(tmp_path)
    predictions_path = data_dir / "predictions.json"
    price_cache_path = data_dir / "price_cache.json"
    monkeypatch.setattr(resolver, "PREDICTIONS_PATH", str(predictions_path))
    monkeypatch.setattr(resolver, "PRICE_CACHE_PATH", str(price_cache_path))
    monkeypatch.setattr(resolver, "_skip_council_learning", lambda *_a, **_k: False)
    assert resolver._in_replay_mode() is False

    resolve_at = datetime.now(timezone.utc) - timedelta(minutes=5)
    stamp = resolve_at.isoformat().replace("+00:00", "Z")
    rows = [
        {
            "id": "tripwire-row",
            "netuid": NETUID,
            "name": "Lock Order Tripwire",
            "direction": "up",
            "predicted_pct": 2.0,
            "reference_price": 100.0,
            "resolve_at": stamp,
            "created_at": (resolve_at - timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
            "status": "pending",
            "horizon_type": "hour",
            "horizon_hours": 1.0,
            "signal_contributions": {"momentum": {"score": 0.9}},
            "active_signals": ["momentum"],
        }
    ]
    predictions_path.write_text(
        json.dumps({"predictions": rows, "resolved": [], "stats": {}}), encoding="utf-8"
    )
    candle = {
        "timestamp": stamp,
        "open": 110.0,
        "high": 110.0,
        "low": 110.0,
        "close": 110.0,
        "volume": 1000.0,
    }
    price_cache_path.write_text(
        json.dumps({str(NETUID): {"candles": [candle]}}), encoding="utf-8"
    )

    monkeypatch.setattr(resolver, "fetch_prices", lambda *_a, **_k: {NETUID: 110.0})
    monkeypatch.setattr(resolver, "hydrate_candles_for_netuid", lambda *_a, **_k: False)
    monkeypatch.setattr(resolver, "hydrate_candles_for_netuid_historical", lambda *_a, **_k: None)
    monkeypatch.setattr(resolver, "_scenario_signals_for_subnet", lambda *_a, **_k: {})
    monkeypatch.setattr(weights, "load_impact_strength", lambda *_a, **_k: 0.5)
    # Open the expert gate so the expert write is reachable. These are inputs, not writes.
    monkeypatch.setattr(
        expert_attribution, "resolve_expert_attribution", lambda *_a, **_k: ("alpha", "existing")
    )
    monkeypatch.setattr(signal_expert, "expert_for_replay_row", lambda *_a, **_k: "alpha")
    monkeypatch.setattr(evidence, "evidence_population", lambda *_a, **_k: "council_published")
    return tmp_path


def _spy(monkeypatch, owner: Any, attr: str, name: str, calls: List[str]) -> None:
    """Record each call to `owner.attr` under `name`, then call the real function."""
    original = getattr(owner, attr)

    def spy(*args, **kwargs):
        calls.append(name)
        return original(*args, **kwargs)

    monkeypatch.setattr(owner, attr, spy)


def _run_pass_under_guard(sched, gen: int):
    """Run one resolver pass on a bound cycle, holding the release guard for the whole pass."""
    errors: List[BaseException] = []

    def worker() -> None:
        timing = resolver_scheduler._CycleTiming()
        timing.set_owner_gen(gen, sched)
        token = resolver_scheduler._cycle_timing.set(timing)
        try:
            with sched._release_guard:
                resolver._resolve_due_predictions(subnets=[{"netuid": NETUID, "price": 110.0}])
        except BaseException as exc:  # surfaced by the assertion below
            errors.append(exc)
        finally:
            resolver_scheduler._cycle_timing.reset(token)

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    thread.join(PASS_TIMEOUT_SECONDS)
    return thread.is_alive(), errors


def test_tripwire_flags_scheduler_lock_acquired_under_release_guard():
    """Control: the wrapper must catch the forbidden order, or the pass test proves nothing."""
    sched = resolver_scheduler.PredictionResolverScheduler()
    violations: List[str] = []
    wrapped = _OrderTripwire("_scheduler_lock", resolver_scheduler._scheduler_lock, sched, violations)

    with sched._release_guard:
        with wrapped:
            pass

    assert violations == ["_scheduler_lock"]


def test_learning_writes_under_release_guard_take_no_scheduler_lock(pass_env, monkeypatch):
    sched = resolver_scheduler.PredictionResolverScheduler()
    sched._persist_owner_gen = 1
    violations: List[str] = []
    monkeypatch.setattr(
        resolver_scheduler,
        "_scheduler_lock",
        _OrderTripwire("_scheduler_lock", resolver_scheduler._scheduler_lock, sched, violations),
    )
    sched._submit_lock = _OrderTripwire("_submit_lock", sched._submit_lock, sched, violations)

    calls: List[str] = []
    _spy(monkeypatch, weights, "nudge_expert", "expert", calls)
    _spy(monkeypatch, resolver, "nudge_impact_strength", "impact", calls)
    _spy(monkeypatch, resolver, "nudge_signal_weight", "signal", calls)
    _spy(monkeypatch, scenario_memory, "record_outcome", "scenario", calls)
    _spy(monkeypatch, resolver, "on_prediction_resolved", "judge", calls)
    _spy(monkeypatch, prediction_trace, "record_prediction_resolved", "trace", calls)
    _spy(monkeypatch, trail_events, "emit_prediction_resolved", "trail", calls)
    _spy(monkeypatch, pick_history, "finalize_from_prediction", "pick_history", calls)
    _spy(monkeypatch, resolver, "atomic_finalize_resolution", "finalize", calls)

    alive, errors = _run_pass_under_guard(sched, gen=1)

    assert not alive, f"resolver pass did not finish within {PASS_TIMEOUT_SECONDS}s (possible deadlock)"
    assert errors == []
    for name in ("expert", "impact", "signal", "scenario", "judge", "trace", "trail", "pick_history", "finalize"):
        assert name in calls, f"{name} never ran, so the pass does not cover it"
    print(f"\n[TRIPWIRE] calls={calls} violations={violations}")
    assert violations == []
