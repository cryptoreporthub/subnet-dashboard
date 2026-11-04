"""Revoked resolver cycles must not reach the learning writers.

Each guarded write site calls the real resolver function here, so the inline
revocation check is exercised, not bypassed by a spy on the function itself.
"""

from __future__ import annotations

import threading
from typing import Any, Dict, List

import pytest

import internal.council.expert_attribution as expert_attribution
import internal.council.pick_history as pick_history
import internal.council.prediction_trace as prediction_trace
import internal.council.resolver as resolver
import internal.council.resolver_scheduler as resolver_scheduler
import internal.council.signal_expert as signal_expert
import internal.learning.evidence as evidence
import internal.learning.trail_events as trail_events


def _bind(sched) -> Any:
    sched._persist_owner_gen = 1
    timing = resolver_scheduler._CycleTiming()
    timing.set_owner_gen(1, sched)
    return resolver_scheduler._cycle_timing.set(timing)


def _prediction() -> Dict[str, Any]:
    return {
        "id": "p1",
        "name": "Guard Test",
        "netuid": 7,
        "direction": "up",
        "predicted_pct": 2.0,
        "horizon_type": "hour",
        "expert": "alpha",
        "signal_contributions": {"rsi": {"score": 0.9}},
        "active_signals": ["rsi"],
    }


@pytest.fixture
def sched(monkeypatch):
    monkeypatch.setattr(resolver, "_skip_council_learning", lambda *_a, **_k: False)
    monkeypatch.setattr(resolver, "_in_replay_mode", lambda: False)
    s = resolver_scheduler.PredictionResolverScheduler()
    token = _bind(s)
    yield s
    resolver_scheduler._cycle_timing.reset(token)


def _recorder(calls: List[str], name: str):
    def spy(*_args, **_kwargs):
        calls.append(name)
        return None

    return spy


def _patch_expert_gate(monkeypatch):
    monkeypatch.setattr(
        expert_attribution, "resolve_expert_attribution", lambda *_a, **_k: ("alpha", "existing")
    )
    monkeypatch.setattr(signal_expert, "expert_for_replay_row", lambda *_a, **_k: "alpha")
    monkeypatch.setattr(evidence, "evidence_population", lambda *_a, **_k: "council_published")


def test_revoked_scenario_write_is_skipped(sched, monkeypatch):
    calls: List[str] = []
    monkeypatch.setattr(resolver.scenario_memory, "record_outcome", _recorder(calls, "scenario"))
    sched._abandon_inflight_cycle()

    resolver._record_scenario_outcome(_prediction(), 3.0, "hit", True, "alpha")

    assert calls == []


def test_live_scenario_write_still_lands(sched, monkeypatch):
    calls: List[str] = []
    monkeypatch.setattr(resolver.scenario_memory, "record_outcome", _recorder(calls, "scenario"))

    resolver._record_scenario_outcome(_prediction(), 3.0, "hit", True, "alpha")

    assert calls == ["scenario"]


def test_revoked_signal_nudge_is_skipped(sched, monkeypatch):
    calls: List[str] = []
    monkeypatch.setattr(resolver, "nudge_signal_weight", _recorder(calls, "signal"))
    sched._abandon_inflight_cycle()

    resolver._nudge_signal_weights(_prediction(), True)

    assert calls == []


def test_live_signal_nudge_still_lands(sched, monkeypatch):
    calls: List[str] = []
    monkeypatch.setattr(resolver, "nudge_signal_weight", _recorder(calls, "signal"))

    resolver._nudge_signal_weights(_prediction(), True)

    assert calls == ["signal"]


def test_revoked_expert_nudge_is_skipped(sched, monkeypatch):
    _patch_expert_gate(monkeypatch)
    calls: List[str] = []
    monkeypatch.setattr(resolver, "_nudge_weights", _recorder(calls, "expert"))
    sched._abandon_inflight_cycle()

    resolver._stamp_and_nudge_expert(_prediction(), correct=True)

    assert calls == []


def test_live_expert_nudge_still_lands(sched, monkeypatch):
    _patch_expert_gate(monkeypatch)
    calls: List[str] = []
    monkeypatch.setattr(resolver, "_nudge_weights", _recorder(calls, "expert"))

    resolver._stamp_and_nudge_expert(_prediction(), correct=True)

    assert calls == ["expert"]


def test_revoked_finalize_writes_nothing(sched, monkeypatch):
    calls: List[str] = []
    monkeypatch.setattr(resolver, "on_prediction_resolved", _recorder(calls, "judge"))
    monkeypatch.setattr(prediction_trace, "record_prediction_resolved", _recorder(calls, "trace"))
    monkeypatch.setattr(trail_events, "emit_prediction_resolved", _recorder(calls, "trail"))
    monkeypatch.setattr(pick_history, "finalize_from_prediction", _recorder(calls, "pick"))
    sched._abandon_inflight_cycle()

    resolver.atomic_finalize_resolution(
        _prediction(),
        actual_pct=3.0,
        outcome="hit",
        correct=True,
        resolved_price=110.0,
        resolved_at="2026-11-04T00:00:00Z",
    )

    assert calls == []


class _ContentionProbe:
    """Release-guard proxy that signals when a thread other than its creator reaches for the guard."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self._creator = threading.get_ident()
        self.contended = threading.Event()

    def acquire(self, blocking: bool = True, timeout: float = -1) -> bool:
        if threading.get_ident() != self._creator:
            self.contended.set()
        return self._inner.acquire(blocking, timeout)

    def release(self) -> None:
        self._inner.release()

    def _is_owned(self) -> bool:
        return self._inner._is_owned()

    def __enter__(self) -> "_ContentionProbe":
        self.acquire()
        return self

    def __exit__(self, *_exc: Any) -> bool:
        self.release()
        return False


def _race_abandon_during_write(sched) -> tuple:
    """Return (seen, abandon_thread, spy).

    The spy runs inside a learning write. It starts abandon, waits until abandon has
    reached the guard, then records whether the write still holds the guard and whether
    abandon is still stuck. Nothing here depends on how fast the thread starts.
    """
    probe = _ContentionProbe(sched._release_guard)
    sched._release_guard = probe
    abandon_thread = threading.Thread(target=sched._abandon_inflight_cycle)
    seen: Dict[str, Any] = {}

    def spy(*_args, **_kwargs):
        seen["revoked_at_write"] = resolver_scheduler.cycle_writes_revoked()
        seen["guard_held_by_write"] = probe._is_owned()
        abandon_thread.start()
        seen["abandon_reached_guard"] = probe.contended.wait(5)
        seen["abandon_blocked"] = abandon_thread.is_alive() and sched._persist_owner_gen is not None
        return None

    return seen, abandon_thread, spy


_RACE_EXPECTED = {
    "revoked_at_write": False,
    "guard_held_by_write": True,
    "abandon_reached_guard": True,
    "abandon_blocked": True,
}


def test_abandon_waits_for_scenario_write_in_flight(sched, monkeypatch):
    """The check and the write sit under the release guard, so abandon cannot slip between them."""
    seen, abandon_thread, spy = _race_abandon_during_write(sched)
    monkeypatch.setattr(resolver.scenario_memory, "record_outcome", spy)

    resolver._record_scenario_outcome(_prediction(), 3.0, "hit", True, "alpha")
    abandon_thread.join(5)

    assert seen == _RACE_EXPECTED
    assert not abandon_thread.is_alive()
    assert sched._persist_owner_gen is None


def test_abandon_waits_for_signal_write_in_flight(sched, monkeypatch):
    seen, abandon_thread, spy = _race_abandon_during_write(sched)
    monkeypatch.setattr(resolver, "nudge_signal_weight", spy)

    resolver._nudge_signal_weights(_prediction(), True)
    abandon_thread.join(5)

    assert seen == _RACE_EXPECTED
    assert not abandon_thread.is_alive()
    assert sched._persist_owner_gen is None


def test_abandon_waits_for_expert_write_in_flight(sched, monkeypatch):
    _patch_expert_gate(monkeypatch)
    seen, abandon_thread, spy = _race_abandon_during_write(sched)
    monkeypatch.setattr(resolver, "_nudge_weights", spy)

    resolver._stamp_and_nudge_expert(_prediction(), correct=True)
    abandon_thread.join(5)

    assert seen == _RACE_EXPECTED
    assert not abandon_thread.is_alive()
    assert sched._persist_owner_gen is None


def _current_price_prediction() -> Dict[str, Any]:
    row = _prediction()
    row["reference_price"] = 100.0
    return row


def _stub_current_price_path(monkeypatch) -> None:
    _patch_expert_gate(monkeypatch)
    monkeypatch.setattr(resolver, "_nudge_weights", lambda *_a, **_k: None)
    monkeypatch.setattr(resolver, "_ensure_subnet_snapshot", lambda *_a, **_k: None)
    monkeypatch.setattr(resolver, "atomic_finalize_resolution", lambda *_a, **_k: None)
    monkeypatch.setattr(resolver, "_record_scenario_outcome", lambda *_a, **_k: None)
    monkeypatch.setattr(resolver, "_nudge_signal_weights", lambda *_a, **_k: None)


def test_revoked_current_price_impact_nudge_is_skipped(sched, monkeypatch):
    _stub_current_price_path(monkeypatch)
    calls: List[str] = []
    monkeypatch.setattr(resolver, "nudge_impact_strength", _recorder(calls, "impact"))
    sched._abandon_inflight_cycle()

    resolver.resolve_prediction(_current_price_prediction(), current_price=102.0)

    assert calls == []


def test_live_current_price_impact_nudge_still_lands(sched, monkeypatch):
    _stub_current_price_path(monkeypatch)
    calls: List[str] = []
    monkeypatch.setattr(resolver, "nudge_impact_strength", lambda *_a, **_k: calls.append("impact") or 0.5)
    monkeypatch.setattr("internal.council.weights.load_impact_strength", lambda *_a, **_k: 0.5)

    resolver.resolve_prediction(_current_price_prediction(), current_price=102.0)

    assert calls == ["impact"]


def test_abandon_waits_for_current_price_impact_write_in_flight(sched, monkeypatch):
    _stub_current_price_path(monkeypatch)
    seen, abandon_thread, spy = _race_abandon_during_write(sched)
    monkeypatch.setattr(resolver, "nudge_impact_strength", lambda *_a, **_k: spy() or 0.5)
    monkeypatch.setattr("internal.council.weights.load_impact_strength", lambda *_a, **_k: 0.5)

    resolver.resolve_prediction(_current_price_prediction(), current_price=102.0)
    abandon_thread.join(5)

    assert seen == _RACE_EXPECTED
    assert not abandon_thread.is_alive()
    assert sched._persist_owner_gen is None
