"""A crash between the resolver's ledger commit and its learning flush must not lose the learning.

The resolver commits a graded row, then runs the learning effects it queued in memory.
If the process dies between the two, the row is resolved on disk and the queue is gone.
A later cycle skips the row as already graded, so the weights never learn from it.

The row carries a durable pending marker, so the expired-recovery sweep re-runs the
effects. These tests crash the flush, run the sweep, and count the real write sinks.
"""

from __future__ import annotations

import fcntl
import json
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest

from internal.council import pick_history, prediction_trace, resolver, scenario_memory, weights
from internal.judges import portfolios
from internal.learning import expired_recovery, predictions_store, trail_bus, trail_events

SINKS = (
    "impact_write",
    "expert_nudge",
    "signal_nudge",
    "judge_resolved",
    "trace_resolved",
    "trail_resolved",
    "pick_finalize",
    "scenario_outcome",
)


class ProcessDied(BaseException):
    """Escapes every `except Exception`, like a killed process."""


def _due_row(row_id: str = "r1") -> dict:
    now = datetime.now(timezone.utc)
    return {
        "id": row_id,
        "netuid": 7,
        "status": "pending",
        "horizon_type": "hour",
        "direction": "long",
        "expert": "oracle",
        "reference_price": 10.0,
        "predicted_pct": 5.0,
        "signal_contributions": {"momentum": {"score": 0.9}},
        "active_signals": ["momentum"],
        "predicted_at": (now - timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
        "resolve_at": (now - timedelta(seconds=60)).isoformat().replace("+00:00", "Z"),
    }


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    path = tmp_path / "predictions.json"
    path.write_text(json.dumps({"predictions": [_due_row()], "resolved": [], "stats": {}}))
    monkeypatch.setattr(resolver, "PREDICTIONS_PATH", str(path))
    monkeypatch.setattr(predictions_store, "PREDICTIONS_PATH", str(path))
    monkeypatch.setattr(resolver, "fetch_prices", lambda _subnets=None: {})
    monkeypatch.setattr(resolver, "hydrate_candles_for_netuid", lambda *_a, **_kw: False)
    monkeypatch.setattr(
        resolver,
        "lookup_horizon_price",
        lambda *_a, **_kw: ("ok", 12.0, {"price_source": "test", "price_lag_seconds": 0}),
    )
    monkeypatch.setattr(resolver, "_skip_council_learning", lambda _prediction: False)
    monkeypatch.setattr(resolver, "_cycle_writes_revoked_safe", lambda: False)
    from internal.council import signal_expert
    from internal.learning import evidence

    monkeypatch.setattr(evidence, "evidence_population", lambda _row: "council_published")
    monkeypatch.setattr(signal_expert, "expert_for_replay_row", lambda _row: "oracle")

    receipts = tmp_path / "learning_effect_receipts.json"
    monkeypatch.setattr(expired_recovery, "LEARNING_EFFECT_RECEIPTS_PATH", str(receipts), raising=False)
    monkeypatch.setenv("LEARNING_EFFECT_RECEIPTS_PATH", str(receipts))
    port_path = tmp_path / "judge_portfolios.json"
    port_path.write_text("{}")
    monkeypatch.setattr(portfolios, "PORTFOLIOS_PATH", str(port_path))
    monkeypatch.setattr(weights, "SOUL_MAP_PATH", str(tmp_path / "soul_map.json"))
    monkeypatch.setattr(trail_bus, "emit_accuracy_update", lambda **_kw: None)
    return path


@pytest.fixture
def sinks(monkeypatch):
    calls: list[str] = []

    def record(name, ret=None):
        def fn(*_a, **_kw):
            calls.append(name)
            return ret

        return fn

    monkeypatch.setattr(resolver, "nudge_impact_strength", record("impact_write", 1.0))
    monkeypatch.setattr(trail_bus, "emit_impact_strength_change", record("impact_trail"))
    monkeypatch.setattr(weights, "nudge_expert", record("expert_nudge", None))
    monkeypatch.setattr(resolver, "nudge_signal_weight", record("signal_nudge"))
    monkeypatch.setattr(resolver, "on_prediction_resolved", record("judge_resolved", {}))
    monkeypatch.setattr(prediction_trace, "record_prediction_resolved", record("trace_resolved"))
    monkeypatch.setattr(trail_events, "emit_prediction_resolved", record("trail_resolved"))
    monkeypatch.setattr(pick_history, "finalize_from_prediction", record("pick_finalize"))
    monkeypatch.setattr(scenario_memory, "record_outcome", record("scenario_outcome"))
    return calls


def _counts(calls):
    return {name: calls.count(name) for name in SINKS}


def _once(rows: int = 1):
    return {name: rows for name in SINKS}


def _markers(ledger_path):
    disk = json.loads(ledger_path.read_text())
    return {r["id"]: r.get("learning_effects") for r in disk["resolved"]}


def _crash_at_flush(monkeypatch):
    def die(*_a, **_kw):
        raise ProcessDied()

    monkeypatch.setattr(resolver, "_flush_deferred_learning", die)


def test_learning_survives_a_crash_between_commit_and_flush(ledger, sinks, monkeypatch):
    _crash_at_flush(monkeypatch)
    with pytest.raises(ProcessDied):
        resolver._resolve_due_predictions(subnets=[])

    disk = json.loads(ledger.read_text())
    assert [r["id"] for r in disk["resolved"]] == ["r1"], "the commit must have landed"
    assert _counts(sinks) == {name: 0 for name in SINKS}, "no learning ran before the crash"

    result = expired_recovery.recover_expired_predictions()

    assert result.get("ok", True), result
    assert _counts(sinks) == _once(), _counts(sinks)


def test_recovered_learning_is_applied_once_across_repeated_sweeps(ledger, sinks, monkeypatch):
    _crash_at_flush(monkeypatch)
    with pytest.raises(ProcessDied):
        resolver._resolve_due_predictions(subnets=[])

    expired_recovery.recover_expired_predictions()
    assert _counts(sinks) == _once()
    expired_recovery.recover_expired_predictions()

    assert _counts(sinks) == _once(), "a second sweep must not apply the effects again"


def test_a_clean_cycle_leaves_nothing_for_the_sweep_to_replay(ledger, sinks):
    resolver._resolve_due_predictions(subnets=[])
    assert _counts(sinks) == _once()

    expired_recovery.recover_expired_predictions()

    assert _counts(sinks) == _once(), "effects that already ran must not run again"


def test_a_clean_cycle_clears_its_markers_on_disk(ledger, sinks):
    resolver._resolve_due_predictions(subnets=[])

    marker = _markers(ledger)["r1"]
    assert marker["pending"] == [], marker
    assert marker["indeterminate"] == [], marker
    assert sorted(marker["done"]) == ["expert", "finalize", "impact", "scenario", "signal"], marker


def test_receipts_alone_stop_the_sweep_when_the_marker_clear_fails(ledger, sinks, monkeypatch):
    def clear_fails(_pairs):
        raise RuntimeError("ledger busy")

    monkeypatch.setattr(expired_recovery, "move_effects_on_ledger", clear_fails)
    resolver._resolve_due_predictions(subnets=[])
    assert _markers(ledger)["r1"]["pending"], "the clear failed, so the markers stay"

    expired_recovery.recover_expired_predictions()

    assert _counts(sinks) == _once(), "receipts must keep the sweep from running the effects again"
    assert _markers(ledger)["r1"]["pending"] == []


def test_the_marker_names_only_the_effects_the_resolver_queued(ledger, sinks, monkeypatch):
    def staging_fails(*_a, **_kw):
        raise RuntimeError("soul map unreadable")

    monkeypatch.setattr(resolver, "_stage_impact_strength", staging_fails)
    _crash_at_flush(monkeypatch)
    with pytest.raises(ProcessDied):
        resolver._resolve_due_predictions(subnets=[])
    assert "impact" not in _markers(ledger)["r1"]["pending"]

    expired_recovery.recover_expired_predictions()

    counts = _counts(sinks)
    assert counts["impact_write"] == 0, "the sweep ran an effect the resolver chose not to queue"
    assert {k: v for k, v in counts.items() if k != "impact_write"} == {
        k: 1 for k in SINKS if k != "impact_write"
    }, counts


def test_crash_after_an_effect_and_before_its_receipt_replays_at_most_that_effect(ledger, sinks, monkeypatch):
    """The accepted residual: the one effect whose receipt was lost can run twice, no other does."""
    real_receipt = expired_recovery.write_effect_receipt
    state = {"calls": 0}

    def die_on_first_receipt(key, effect):
        state["calls"] += 1
        if state["calls"] == 1:
            raise ProcessDied()
        return real_receipt(key, effect)

    monkeypatch.setattr(expired_recovery, "write_effect_receipt", die_on_first_receipt)
    with pytest.raises(ProcessDied):
        resolver._resolve_due_predictions(subnets=[])
    expired_recovery.recover_expired_predictions()

    counts = _counts(sinks)
    assert 1 <= counts["expert_nudge"] <= 2, counts
    assert {k: v for k, v in counts.items() if k != "expert_nudge"} == {
        k: 1 for k in SINKS if k != "expert_nudge"
    }, counts


def test_an_effect_that_raises_is_retried_by_the_sweep_and_the_rest_are_not_repeated(ledger, sinks, monkeypatch):
    state = {"raised": False}

    def expert_fails_once(*_a, **_kw):
        if not state["raised"]:
            state["raised"] = True
            raise RuntimeError("weights file busy")
        sinks.append("expert_nudge")

    monkeypatch.setattr(weights, "nudge_expert", expert_fails_once)
    resolver._resolve_due_predictions(subnets=[])
    assert _counts(sinks)["expert_nudge"] == 0
    assert _counts(sinks)["signal_nudge"] == 1

    expired_recovery.recover_expired_predictions()

    assert _counts(sinks) == _once(), _counts(sinks)


def test_learning_dropped_by_a_revoke_is_recovered_by_the_sweep(ledger, sinks, monkeypatch):
    state = {"rev": False}
    monkeypatch.setattr(resolver, "_cycle_writes_revoked_safe", lambda: state["rev"])

    def expert_then_revoke(*_a, **_kw):
        sinks.append("expert_nudge")
        state["rev"] = True

    monkeypatch.setattr(weights, "nudge_expert", expert_then_revoke)
    resolver._resolve_due_predictions(subnets=[])
    assert _counts(sinks)["signal_nudge"] == 0

    state["rev"] = False
    expired_recovery.recover_expired_predictions()

    assert _counts(sinks) == _once(), _counts(sinks)


NETUID = 7


@pytest.fixture
def regrade_ledger(tmp_path, monkeypatch, ledger):
    """An expired row that now has a candle, so regrade_expired_predictions grades it."""
    resolve_at = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat().replace("+00:00", "Z")
    expired = {
        "id": "regrade-1",
        "netuid": NETUID,
        "name": "Regrade Test",
        "direction": "up",
        "predicted_pct": 2.0,
        "reference_price": 100.0,
        "resolve_at": resolve_at,
        "created_at": resolve_at,
        "status": "expired",
        "outcome": "expired",
        "horizon_type": "hour",
        "expert": "oracle",
        "signal_contributions": {"momentum": {"score": 0.9}},
        "active_signals": ["momentum"],
    }
    ledger.write_text(json.dumps({"predictions": [], "resolved": [expired], "stats": {}}))
    cache = tmp_path / "price_cache.json"
    cache.write_text(json.dumps({
        str(NETUID): {
            "source": "test",
            "candles": [{
                "timestamp": resolve_at, "open": 102.0, "high": 103.0,
                "low": 101.0, "close": 103.0, "volume": 500.0,
            }],
        }
    }))
    monkeypatch.setattr(resolver, "PRICE_CACHE_PATH", str(cache))
    monkeypatch.setattr(weights, "SOUL_MAP_PATH", str(tmp_path / "soul_map.json"))
    return ledger


def test_regraded_row_learning_survives_a_crash_between_commit_and_flush(regrade_ledger, sinks, monkeypatch):
    _crash_at_flush(monkeypatch)
    with pytest.raises(ProcessDied):
        resolver.regrade_expired_predictions(live_prices={})

    disk = json.loads(regrade_ledger.read_text())
    assert disk["resolved"][0]["outcome"] != "expired", "the regrade commit must have landed"
    assert _counts(sinks) == {name: 0 for name in SINKS}, "no learning ran before the crash"

    expired_recovery.recover_expired_predictions()
    once = _counts(sinks)
    expired_recovery.recover_expired_predictions()

    assert _counts(sinks) == once, "a second sweep must not apply the effects again"
    assert once == _once(), once


def _second_due_row():
    row = _due_row("r2")
    row["netuid"] = 8
    return row


def test_a_sweep_that_overlaps_the_flush_does_not_apply_an_effect_twice(ledger, sinks, monkeypatch):
    """The row is committed with its marker before the flush ends, so the sweep can see it."""
    monkeypatch.setattr(expired_recovery, "APPLY_LOCK_TIMEOUT_SECONDS", 0.3)
    in_flush = threading.Event()
    release = threading.Event()
    state = {"first": True}

    def expert_blocks_once(*_a, **_kw):
        sinks.append("expert_nudge")
        if state["first"]:
            state["first"] = False
            in_flush.set()
            release.wait(timeout=20)

    monkeypatch.setattr(weights, "nudge_expert", expert_blocks_once)
    flush = threading.Thread(target=lambda: resolver._resolve_due_predictions(subnets=[]))
    flush.start()
    try:
        assert in_flush.wait(timeout=20), "the flush never reached its first effect"
        expired_recovery.recover_expired_predictions()
    finally:
        release.set()
        flush.join(timeout=30)
    assert not flush.is_alive()
    expired_recovery.recover_expired_predictions()

    assert _counts(sinks) == _once(), _counts(sinks)


def test_a_held_receipts_lock_does_not_stall_the_cycle_and_loses_no_learning(
    ledger, sinks, monkeypatch, tmp_path
):
    """The flush gives up at the first receipts-lock timeout. The sweep finishes the work later."""
    ledger.write_text(
        json.dumps({"predictions": [_due_row(), _second_due_row()], "resolved": [], "stats": {}})
    )
    monkeypatch.setattr(expired_recovery, "RECEIPTS_LOCK_TIMEOUT_SECONDS", 0.2)
    real_lock = expired_recovery._receipts_lock
    attempts = {"n": 0}

    @contextmanager
    def counted(**kwargs):
        attempts["n"] += 1
        with real_lock(**kwargs) as value:
            yield value

    monkeypatch.setattr(expired_recovery, "_receipts_lock", counted)
    lock_path = str(tmp_path / "learning_effect_receipts.json") + ".lock"
    with open(lock_path, "a+", encoding="utf-8") as held:
        fcntl.flock(held.fileno(), fcntl.LOCK_EX)
        try:
            resolver._resolve_due_predictions(subnets=[])
            waited = attempts["n"]
        finally:
            fcntl.flock(held.fileno(), fcntl.LOCK_UN)

    assert waited <= 2, f"the flush waited on the receipts lock {waited} times"

    expired_recovery.recover_expired_predictions()
    assert _counts(sinks) == _once(rows=2), _counts(sinks)
