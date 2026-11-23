"""A crash between the resolver's ledger commit and its learning flush must not lose the learning.

The resolver commits a graded row, then runs the learning effects it queued in memory.
If the process dies between the two, the row is resolved on disk and the queue is gone.
A later cycle skips the row as already graded, so the weights never learn from it.

The row carries a durable pending marker, so the expired-recovery sweep re-runs the
effects. These tests crash the flush, run the sweep, and count the real write sinks.
"""

from __future__ import annotations

import errno
import fcntl
import json
import logging
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


def test_an_unreadable_receipts_file_does_not_stop_live_learning(ledger, sinks, tmp_path):
    (tmp_path / "learning_effect_receipts.json").write_text("not json {")

    resolver._resolve_due_predictions(subnets=[])

    assert _counts(sinks) == _once(), "learning must still run when the journal is unreadable"
    marker = _markers(ledger)["r1"]
    assert marker["pending"] == [], marker
    assert sorted(marker["indeterminate"]) == ["expert", "finalize", "impact", "scenario", "signal"], marker

    expired_recovery.recover_expired_predictions()

    assert _counts(sinks) == _once(), "the sweep must not run effects while the journal is unreadable"


def test_a_sweep_that_finishes_before_the_flush_starts_is_not_repeated(ledger, sinks, monkeypatch):
    """The recheck under the lock is what stops the flush from repeating work the sweep did."""
    in_flush = threading.Event()
    release = threading.Event()
    real_flush = resolver._flush_deferred_learning

    def flush_after_the_sweep(deferral, commit_result):
        in_flush.set()
        release.wait(timeout=20)
        real_flush(deferral, commit_result)

    monkeypatch.setattr(resolver, "_flush_deferred_learning", flush_after_the_sweep)
    cycle = threading.Thread(target=lambda: resolver._resolve_due_predictions(subnets=[]))
    cycle.start()
    try:
        assert in_flush.wait(timeout=20), "the cycle never reached its flush"
        expired_recovery.recover_expired_predictions()
        assert _counts(sinks) == _once(), "the sweep should have run every effect"
    finally:
        release.set()
        cycle.join(timeout=30)
    assert not cycle.is_alive()

    assert _counts(sinks) == _once(), _counts(sinks)


def test_a_queued_effect_with_no_row_key_still_runs_once(monkeypatch):
    """No committed row has an empty key, so this pins the flush's own behavior directly."""
    from types import SimpleNamespace

    monkeypatch.setattr(resolver, "_cycle_writes_revoked_safe", lambda: False)
    ran: list[str] = []
    deferral = resolver._LearningDeferral()
    deferral.items.append((None, "expert", lambda: ran.append("expert"), {}))

    resolver._flush_deferred_learning(deferral, SimpleNamespace(conflicts=()))

    assert ran == ["expert"]


def _two_rows(ledger_path):
    ledger_path.write_text(
        json.dumps({"predictions": [_due_row(), _second_due_row()], "resolved": [], "stats": {}})
    )


def _count_calls(monkeypatch, name):
    real = getattr(expired_recovery, name)
    calls = {"n": 0}

    @contextmanager
    def counted(*args, **kwargs):
        calls["n"] += 1
        with real(*args, **kwargs) as value:
            yield value

    monkeypatch.setattr(expired_recovery, name, counted)
    return calls


def test_a_held_apply_lock_stops_the_flush_at_the_first_timeout(ledger, sinks, monkeypatch, tmp_path):
    _two_rows(ledger)
    monkeypatch.setattr(expired_recovery, "APPLY_LOCK_TIMEOUT_SECONDS", 0.2)
    attempts = _count_calls(monkeypatch, "_apply_lock")
    apply_path = str(tmp_path / "learning_effect_receipts.json") + ".apply"
    with open(apply_path, "a+") as held:
        fcntl.flock(held.fileno(), fcntl.LOCK_EX)
        try:
            resolver._resolve_due_predictions(subnets=[])
        finally:
            fcntl.flock(held.fileno(), fcntl.LOCK_UN)

    assert attempts["n"] == 1, f"the flush kept waiting on the apply lock {attempts['n']} times"
    expired_recovery.recover_expired_predictions()
    assert _counts(sinks) == _once(rows=2), _counts(sinks)


def test_effects_with_no_row_key_each_run_and_share_no_receipt(monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr(resolver, "_cycle_writes_revoked_safe", lambda: False)
    ran: list[str] = []
    for _cycle in range(2):
        deferral = resolver._LearningDeferral()
        deferral.items.append((None, "expert", lambda: ran.append("expert"), {}))
        resolver._flush_deferred_learning(deferral, SimpleNamespace(conflicts=()))

    assert ran == ["expert", "expert"]


def test_the_receipt_is_written_before_the_sweep_can_take_the_apply_lock(ledger, sinks, monkeypatch):
    monkeypatch.setattr(expired_recovery, "APPLY_LOCK_TIMEOUT_SECONDS", 0.3)
    real_write = expired_recovery.write_effect_receipt
    at_receipt = threading.Event()
    release = threading.Event()
    state = {"first": True}

    def slow_first_receipt(key, effect):
        if state["first"]:
            state["first"] = False
            at_receipt.set()
            release.wait(timeout=20)
        return real_write(key, effect)

    monkeypatch.setattr(expired_recovery, "write_effect_receipt", slow_first_receipt)
    cycle = threading.Thread(target=lambda: resolver._resolve_due_predictions(subnets=[]))
    cycle.start()
    try:
        assert at_receipt.wait(timeout=20)
        expired_recovery.recover_expired_predictions()
    finally:
        release.set()
        cycle.join(timeout=30)
    expired_recovery.recover_expired_predictions()

    assert _counts(sinks) == _once(), _counts(sinks)


def test_a_receipt_write_timeout_after_an_effect_stops_the_flush(ledger, sinks, monkeypatch, tmp_path):
    """A shared lock lets the receipt recheck pass, so the write is what times out."""
    monkeypatch.setattr(expired_recovery, "RECEIPTS_LOCK_TIMEOUT_SECONDS", 0.2)
    lock_path = str(tmp_path / "learning_effect_receipts.json") + ".lock"
    with open(lock_path, "a+") as held:
        fcntl.flock(held.fileno(), fcntl.LOCK_SH)
        try:
            resolver._resolve_due_predictions(subnets=[])
        finally:
            fcntl.flock(held.fileno(), fcntl.LOCK_UN)

    marker = _markers(ledger)["r1"]
    assert marker["indeterminate"] == ["expert"], marker
    assert sorted(marker["pending"]) == ["finalize", "impact", "scenario", "signal"], marker


def test_markers_of_effects_receipted_before_a_stop_are_cleared(ledger, sinks, monkeypatch):
    real_has = expired_recovery.has_effect_receipt
    calls = {"n": 0}

    def second_recheck_times_out(key, effect):
        calls["n"] += 1
        if calls["n"] == 2:
            raise expired_recovery.LearningEffectReceiptsLockTimeout("held")
        return real_has(key, effect)

    monkeypatch.setattr(expired_recovery, "has_effect_receipt", second_recheck_times_out)
    resolver._resolve_due_predictions(subnets=[])

    marker = _markers(ledger)["r1"]
    assert marker["done"] == ["expert"], marker
    assert "expert" not in marker["pending"], marker


def test_the_flush_rechecks_the_receipt_after_it_takes_the_apply_lock(ledger, sinks, monkeypatch):
    monkeypatch.setattr(expired_recovery, "APPLY_LOCK_TIMEOUT_SECONDS", 5.0)
    real_lock = expired_recovery._apply_lock
    at_lock = threading.Event()
    release = threading.Event()
    state = {"first": True}

    @contextmanager
    def pause_flush_once(*args, **kwargs):
        if threading.current_thread().name == "flush" and state["first"]:
            state["first"] = False
            at_lock.set()
            release.wait(timeout=20)
        with real_lock(*args, **kwargs) as value:
            yield value

    monkeypatch.setattr(expired_recovery, "_apply_lock", pause_flush_once)
    cycle = threading.Thread(
        target=lambda: resolver._resolve_due_predictions(subnets=[]), name="flush"
    )
    cycle.start()
    try:
        assert at_lock.wait(timeout=20)
        expired_recovery.recover_expired_predictions()
    finally:
        release.set()
        cycle.join(timeout=30)

    assert _counts(sinks) == _once(), _counts(sinks)


def test_an_unexpected_error_from_the_journal_does_not_abort_the_cycle(ledger, sinks, monkeypatch, tmp_path):
    """A path under a regular file makes the real lock-file open raise NotADirectoryError."""
    blocker = tmp_path / "blocker"
    blocker.write_text("a regular file")
    good = str(tmp_path / "learning_effect_receipts.json")
    bad = str(blocker / "receipts.json")
    monkeypatch.setenv("LEARNING_EFFECT_RECEIPTS_PATH", bad)
    monkeypatch.setattr(expired_recovery, "LEARNING_EFFECT_RECEIPTS_PATH", bad, raising=False)

    resolver._resolve_due_predictions(subnets=[])

    assert [r["id"] for r in json.loads(ledger.read_text())["resolved"]] == ["r1"], "the commit must stay"
    assert _markers(ledger)["r1"]["pending"], "the effects must stay pending"

    monkeypatch.setenv("LEARNING_EFFECT_RECEIPTS_PATH", good)
    monkeypatch.setattr(expired_recovery, "LEARNING_EFFECT_RECEIPTS_PATH", good, raising=False)
    expired_recovery.recover_expired_predictions()

    assert _counts(sinks) == _once(), _counts(sinks)


def _lock_failing_on_entry(monkeypatch, entry, error):
    real_lock = expired_recovery._apply_lock
    state = {"n": 0}

    @contextmanager
    def failing(*args, **kwargs):
        state["n"] += 1
        if state["n"] == entry:
            raise error
        with real_lock(*args, **kwargs) as value:
            yield value

    monkeypatch.setattr(expired_recovery, "_apply_lock", failing)
    return real_lock


def test_an_unexpected_error_stops_the_flush_and_keeps_what_already_ran(ledger, sinks, monkeypatch):
    real_lock = _lock_failing_on_entry(monkeypatch, 2, OSError(28, "No space left on device"))

    resolver._resolve_due_predictions(subnets=[])

    marker = _markers(ledger)["r1"]
    assert marker["done"] == ["expert"], marker
    assert sorted(marker["pending"]) == ["finalize", "impact", "scenario", "signal"], marker
    counts = _counts(sinks)
    assert counts["expert_nudge"] == 1 and counts["signal_nudge"] == 0, counts
    assert counts["judge_resolved"] == 0, counts

    monkeypatch.setattr(expired_recovery, "_apply_lock", real_lock)
    expired_recovery.recover_expired_predictions()

    assert _counts(sinks) == _once(), _counts(sinks)


def test_an_error_that_is_not_an_oserror_does_not_abort_the_cycle_either(ledger, sinks, monkeypatch):
    real_lock = _lock_failing_on_entry(monkeypatch, 1, RuntimeError("lock backend failed"))

    resolver._resolve_due_predictions(subnets=[])

    assert [r["id"] for r in json.loads(ledger.read_text())["resolved"]] == ["r1"]
    assert len(_markers(ledger)["r1"]["pending"]) == 5
    assert _counts(sinks) == {name: 0 for name in SINKS}

    monkeypatch.setattr(expired_recovery, "_apply_lock", real_lock)
    expired_recovery.recover_expired_predictions()

    assert _counts(sinks) == _once(), _counts(sinks)


@pytest.fixture
def judges(ledger, sinks, monkeypatch, tmp_path):
    """Real judge close and nudge: positions open for r1 and regrade-1, nudge_judge is spied."""
    import internal.judges.postmortems as postmortems
    import internal.judges.weights as judge_weights
    from internal.judges import tracker

    monkeypatch.setattr(postmortems, "POSTMORTEMS_DIR", str(tmp_path / "postmortems"))
    monkeypatch.setattr(resolver, "on_prediction_resolved", tracker.on_prediction_resolved)
    nudges: list[str] = []
    monkeypatch.setattr(judge_weights, "nudge_judge", lambda name, *_a, **_k: nudges.append(name))
    for row in (_due_row(), _due_row("regrade-1")):
        for judge in tracker.all_judges():
            judge.open_position(row, size=1.0)
    return nudges


def _judge_count():
    from internal.judges import tracker

    return len(tracker.all_judges())


def test_a_crash_before_the_flush_still_nudges_each_judge_once(judges, monkeypatch):
    _crash_at_flush(monkeypatch)
    with pytest.raises(ProcessDied):
        resolver._resolve_due_predictions(subnets=[])
    assert judges == []

    expired_recovery.recover_expired_predictions()

    assert len(judges) == _judge_count(), judges


def test_a_clean_cycle_nudges_each_judge_once_and_the_sweep_adds_none(judges):
    resolver._resolve_due_predictions(subnets=[])
    assert len(judges) == _judge_count(), judges

    expired_recovery.recover_expired_predictions()

    assert len(judges) == _judge_count(), "the sweep must not nudge a judge again"


def test_a_regrade_crash_replays_without_a_judge_nudge(regrade_ledger, judges, monkeypatch):
    _crash_at_flush(monkeypatch)
    with pytest.raises(ProcessDied):
        resolver.regrade_expired_predictions(live_prices={})

    expired_recovery.recover_expired_predictions()

    assert judges == [], "regrade grades with apply_judge_nudge False, so replay must too"


def test_a_lock_timeout_stop_before_finalize_still_nudges_each_judge_once(judges, monkeypatch):
    real_has = expired_recovery.has_effect_receipt

    def finalize_times_out(key, effect):
        if effect == "finalize":
            raise expired_recovery.LearningEffectReceiptsLockTimeout("held")
        return real_has(key, effect)

    monkeypatch.setattr(expired_recovery, "has_effect_receipt", finalize_times_out)
    resolver._resolve_due_predictions(subnets=[])
    assert judges == []
    monkeypatch.setattr(expired_recovery, "has_effect_receipt", real_has)

    expired_recovery.recover_expired_predictions()

    assert len(judges) == _judge_count(), judges


def test_a_failed_receipt_write_marks_that_effect_indeterminate_and_the_flush_goes_on(
    ledger, sinks, monkeypatch
):
    real_write = expired_recovery.write_effect_receipt
    state = {"first": True}

    def first_write_fails(key, effect):
        if state["first"]:
            state["first"] = False
            raise OSError(errno.EIO, "input/output error")
        return real_write(key, effect)

    monkeypatch.setattr(expired_recovery, "write_effect_receipt", first_write_fails)
    resolver._resolve_due_predictions(subnets=[])

    marker = _markers(ledger)["r1"]
    assert marker["indeterminate"] == ["expert"], marker
    assert sorted(marker["done"]) == ["finalize", "impact", "scenario", "signal"], marker
    assert _counts(sinks) == _once(), "later effects must still run live"

    expired_recovery.recover_expired_predictions()

    assert _counts(sinks) == _once(), "the sweep must settle the indeterminate effect without running it"
    assert _markers(ledger)["r1"]["indeterminate"] == []


def test_a_trace_write_failure_is_a_warning_and_finalize_is_done_in_the_live_path_too(
    ledger, sinks, monkeypatch, caplog
):
    from internal.council import prediction_trace

    def trace_fails(*_a, **_kw):
        raise RuntimeError("trace disk unavailable")

    monkeypatch.setattr(prediction_trace, "record_prediction_resolved", trace_fails)
    with caplog.at_level(logging.WARNING):
        resolver._resolve_due_predictions(subnets=[])

    marker = _markers(ledger)["r1"]
    assert "finalize" in marker["done"], marker
    assert any(r.levelno >= logging.WARNING and "r1" in r.getMessage() for r in caplog.records)


def test_a_replayed_pump_calibration_gets_the_prediction_the_live_effect_got(ledger, sinks, monkeypatch):
    from internal.learning import pump_calibration

    seen: list[object] = []
    monkeypatch.setattr(
        pump_calibration,
        "maybe_adapt_after_resolve",
        lambda *a, prediction=None, **k: seen.append(prediction),
    )
    monkeypatch.setattr(resolver, "_skip_council_learning", lambda _row: True)

    resolver._resolve_due_predictions(subnets=[])
    live = list(seen)
    assert len(live) == 1 and live[0] is not None and live[0]["id"] == "r1", live

    seen.clear()
    ledger.write_text(
        json.dumps({"predictions": [_second_due_row()], "resolved": [], "stats": {}})
    )
    _crash_at_flush(monkeypatch)
    with pytest.raises(ProcessDied):
        resolver._resolve_due_predictions(subnets=[])
    assert seen == []

    expired_recovery.recover_expired_predictions()

    assert len(seen) == 1 and seen[0] is not None and seen[0]["id"] == "r2", seen


def test_a_row_recovered_from_expired_replays_pump_calibration_as_before(ledger, sinks, monkeypatch):
    """Only resolver-stamped rows replay with the prediction. Recovered rows keep the old call."""
    from internal.council import price_reference
    from internal.learning import pump_calibration

    seen: list[object] = ["unset"]
    seen.clear()
    monkeypatch.setattr(
        pump_calibration,
        "maybe_adapt_after_resolve",
        lambda *a, prediction=None, **k: seen.append(prediction),
    )
    monkeypatch.setattr(resolver, "_skip_council_learning", lambda _row: True)
    monkeypatch.setattr(
        price_reference, "price_at_resolve_at", lambda *a, **k: ("ok", 110.0, {"price_source": "hourly"})
    )
    expired = {
        "id": "expired-1",
        "netuid": 7,
        "status": "expired",
        "outcome": "expired",
        "correct": None,
        "direction": "up",
        "reference_price": 100.0,
        "predicted_pct": 5.0,
        "resolve_at": "2026-07-01T12:00:00Z",
    }
    ledger.write_text(json.dumps({"predictions": [], "resolved": [expired], "stats": {}}))

    result = expired_recovery.recover_expired_predictions()

    assert result.get("recovered") == 1, result
    assert seen == [None], seen


def _spy_pump(monkeypatch):
    from internal.learning import pump_calibration

    seen: list = []
    monkeypatch.setattr(
        pump_calibration,
        "maybe_adapt_after_resolve",
        lambda *a, prediction=None, **k: seen.append(prediction),
    )
    monkeypatch.setattr(resolver, "_skip_council_learning", lambda _row: True)
    return seen


def test_a_regrade_crash_replays_pump_calibration_with_the_regraded_row(regrade_ledger, sinks, monkeypatch):
    seen = _spy_pump(monkeypatch)
    _crash_at_flush(monkeypatch)
    with pytest.raises(ProcessDied):
        resolver.regrade_expired_predictions(live_prices={})
    assert seen == []

    expired_recovery.recover_expired_predictions()

    assert len(seen) == 1 and seen[0] is not None and seen[0]["id"] == "regrade-1", seen


def test_a_replayed_pump_calibration_gets_the_graded_row_not_just_its_id(ledger, sinks, monkeypatch):
    seen = _spy_pump(monkeypatch)
    _crash_at_flush(monkeypatch)
    with pytest.raises(ProcessDied):
        resolver._resolve_due_predictions(subnets=[])

    expired_recovery.recover_expired_predictions()

    assert len(seen) == 1, seen
    row = seen[0]
    assert row["id"] == "r1" and row.get("outcome") and row.get("actual_pct") is not None, row


def test_a_finalize_that_a_second_sweep_retries_still_nudges_each_judge(judges, monkeypatch):
    real_close = resolver.on_prediction_resolved
    state = {"failed": False}

    def close_fails_once(prediction, **kwargs):
        if not state["failed"]:
            state["failed"] = True
            raise RuntimeError("portfolio write busy")
        return real_close(prediction, **kwargs)

    _crash_at_flush(monkeypatch)
    with pytest.raises(ProcessDied):
        resolver._resolve_due_predictions(subnets=[])
    monkeypatch.setattr(resolver, "on_prediction_resolved", close_fails_once)

    expired_recovery.recover_expired_predictions()
    assert judges == [], judges
    expired_recovery.recover_expired_predictions()

    assert len(judges) == _judge_count(), judges


def test_an_indeterminate_mark_keeps_the_judge_flag_for_a_finalize_stopped_later(judges, monkeypatch):
    real_write = expired_recovery.write_effect_receipt
    real_has = expired_recovery.has_effect_receipt
    state = {"first": True}

    def first_write_fails(key, effect):
        if state["first"]:
            state["first"] = False
            raise OSError(errno.EIO, "input/output error")
        return real_write(key, effect)

    def finalize_times_out(key, effect):
        if effect == "finalize":
            raise expired_recovery.LearningEffectReceiptsLockTimeout("held")
        return real_has(key, effect)

    monkeypatch.setattr(expired_recovery, "write_effect_receipt", first_write_fails)
    monkeypatch.setattr(expired_recovery, "has_effect_receipt", finalize_times_out)
    resolver._resolve_due_predictions(subnets=[])
    assert judges == []
    monkeypatch.setattr(expired_recovery, "write_effect_receipt", real_write)
    monkeypatch.setattr(expired_recovery, "has_effect_receipt", real_has)

    expired_recovery.recover_expired_predictions()

    assert len(judges) == _judge_count(), judges


def test_a_later_cycle_leaves_an_older_rows_marker_alone(ledger, sinks, monkeypatch):
    real_write = expired_recovery.write_effect_receipt
    state = {"first": True}

    def first_write_fails(key, effect):
        if state["first"]:
            state["first"] = False
            raise OSError(errno.EIO, "input/output error")
        return real_write(key, effect)

    monkeypatch.setattr(expired_recovery, "write_effect_receipt", first_write_fails)
    resolver._resolve_due_predictions(subnets=[])
    before = _markers(ledger)["r1"]
    assert before["indeterminate"] == ["expert"], before

    disk = json.loads(ledger.read_text())
    disk["predictions"] = [_second_due_row()]
    ledger.write_text(json.dumps(disk))
    resolver._resolve_due_predictions(subnets=[])

    assert _markers(ledger)["r1"] == before, _markers(ledger)["r1"]


def test_a_row_recovered_from_expired_closes_judge_positions_without_a_nudge(judges, ledger, monkeypatch):
    from internal.council import price_reference
    from internal.judges import tracker

    monkeypatch.setattr(
        price_reference, "price_at_resolve_at", lambda *a, **k: ("ok", 110.0, {"price_source": "hourly"})
    )
    expired = {
        "id": "expired-1",
        "netuid": 7,
        "status": "expired",
        "outcome": "expired",
        "correct": None,
        "direction": "up",
        "reference_price": 100.0,
        "predicted_pct": 5.0,
        "expert": "oracle",
        "resolve_at": "2026-07-01T12:00:00Z",
    }
    for judge in tracker.all_judges():
        judge.open_position(expired, size=1.0)
    ledger.write_text(json.dumps({"predictions": [], "resolved": [expired], "stats": {}}))

    result = expired_recovery.recover_expired_predictions()

    assert result.get("recovered") == 1, result
    assert judges == [], "a recovered expired row has always replayed without the judge nudge"


def _row_on_disk(ledger_path, row_id):
    return next(r for r in json.loads(ledger_path.read_text())["resolved"] if r["id"] == row_id)


def test_a_trace_write_failure_is_stamped_on_the_saved_row_as_before(ledger, sinks, monkeypatch):
    """The row used to carry side_effect_warnings, and an audit script reads that field."""
    from internal.council import prediction_trace

    def trace_fails(*_a, **_kw):
        raise RuntimeError("trace disk unavailable")

    monkeypatch.setattr(prediction_trace, "record_prediction_resolved", trace_fails)
    resolver._resolve_due_predictions(subnets=[])

    row = _row_on_disk(ledger, "r1")
    assert row.get("side_effect_warnings") == ["record_prediction_resolved"], row.get("side_effect_warnings")
    assert _markers(ledger)["r1"]["pending"] == []


def test_a_clean_cycle_leaves_no_side_effect_warnings_on_the_row(ledger, sinks):
    resolver._resolve_due_predictions(subnets=[])

    assert "side_effect_warnings" not in _row_on_disk(ledger, "r1")


def test_a_regrade_trace_failure_is_stamped_on_the_saved_row_too(regrade_ledger, sinks, monkeypatch):
    from internal.council import prediction_trace

    monkeypatch.setattr(
        prediction_trace, "record_prediction_resolved", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("trace"))
    )
    resolver.regrade_expired_predictions(live_prices={})

    row = _row_on_disk(regrade_ledger, "regrade-1")
    assert row.get("side_effect_warnings") == ["record_prediction_resolved"], row.get("side_effect_warnings")


def test_a_trace_failure_is_stamped_even_when_no_receipt_could_be_written(ledger, sinks, monkeypatch):
    from internal.council import prediction_trace

    def receipts_unwritable(key, effect):
        raise OSError(errno.EIO, "input/output error")

    monkeypatch.setattr(
        prediction_trace, "record_prediction_resolved", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("trace"))
    )
    monkeypatch.setattr(expired_recovery, "write_effect_receipt", receipts_unwritable)
    resolver._resolve_due_predictions(subnets=[])

    assert _row_on_disk(ledger, "r1").get("side_effect_warnings") == ["record_prediction_resolved"]


def test_warnings_are_stamped_only_on_the_row_that_reported_them(ledger, sinks, monkeypatch):
    from internal.council import prediction_trace

    real = prediction_trace.record_prediction_resolved

    def trace_fails_for_r1(prediction, *a, **k):
        if prediction.get("id") == "r1":
            raise RuntimeError("trace")
        return real(prediction, *a, **k)

    monkeypatch.setattr(prediction_trace, "record_prediction_resolved", trace_fails_for_r1)
    _two_rows(ledger)
    resolver._resolve_due_predictions(subnets=[])

    assert _row_on_disk(ledger, "r1").get("side_effect_warnings") == ["record_prediction_resolved"]
    assert "side_effect_warnings" not in _row_on_disk(ledger, "r2")


def _flush_leaves_finalize_pending_with_a_stamped_close_failure(monkeypatch):
    """Close fails live, then the receipt write and the indeterminate mark both fail."""

    close_calls = []

    def close_fails(*_a, **_kw):
        close_calls.append(1)
        raise RuntimeError("portfolio write busy")

    real_write = expired_recovery.write_effect_receipt

    def finalize_receipt_fails(key, effect):
        if effect == "finalize":
            raise OSError(errno.EIO, "input/output error")
        return real_write(key, effect)

    def mark_fails(*_a, **_kw):
        raise OSError(errno.EIO, "input/output error")

    monkeypatch.setattr(resolver, "on_prediction_resolved", close_fails)
    monkeypatch.setattr(expired_recovery, "write_effect_receipt", finalize_receipt_fails)
    monkeypatch.setattr(expired_recovery, "_mark_effect_indeterminate", mark_fails)
    return close_calls, real_write


def test_a_close_failure_that_repeats_on_replay_keeps_finalize_pending(ledger, sinks, monkeypatch):
    close_calls, real_write = _flush_leaves_finalize_pending_with_a_stamped_close_failure(monkeypatch)
    resolver._resolve_due_predictions(subnets=[])
    assert _markers(ledger)["r1"]["pending"] == ["finalize"]
    assert "on_prediction_resolved" in _row_on_disk(ledger, "r1")["side_effect_warnings"]
    monkeypatch.setattr(expired_recovery, "write_effect_receipt", real_write)
    attempts_before_sweep = len(close_calls)

    result = expired_recovery.recover_expired_predictions()

    assert len(close_calls) > attempts_before_sweep, "the sweep must have replayed finalize"
    assert result.get("ok") is False, "the replayed close failed again, so the sweep must stay incomplete"
    assert "finalize" in _markers(ledger)["r1"]["pending"]


def test_a_stale_stamped_warning_is_cleared_when_the_replay_succeeds(ledger, sinks, monkeypatch):
    from internal.judges import tracker

    _close_calls, real_write = _flush_leaves_finalize_pending_with_a_stamped_close_failure(monkeypatch)
    resolver._resolve_due_predictions(subnets=[])
    assert "on_prediction_resolved" in _row_on_disk(ledger, "r1")["side_effect_warnings"]
    monkeypatch.setattr(expired_recovery, "write_effect_receipt", real_write)
    monkeypatch.setattr(resolver, "on_prediction_resolved", tracker.on_prediction_resolved)

    expired_recovery.recover_expired_predictions()

    assert _markers(ledger)["r1"]["pending"] == []
    assert "side_effect_warnings" not in _row_on_disk(ledger, "r1")


def test_a_stamped_trace_warning_is_cleared_when_a_healthy_replay_finishes_finalize(ledger, sinks, monkeypatch):
    from internal.council import prediction_trace

    real_trace = prediction_trace.record_prediction_resolved
    real_write = expired_recovery.write_effect_receipt
    real_mark = expired_recovery._mark_effect_indeterminate

    def io_error(*_a, **_kw):
        raise OSError(errno.EIO, "input/output error")

    monkeypatch.setattr(
        expired_recovery,
        "write_effect_receipt",
        lambda key, effect: io_error() if effect == "finalize" else real_write(key, effect),
    )
    monkeypatch.setattr(expired_recovery, "_mark_effect_indeterminate", io_error)
    monkeypatch.setattr(
        prediction_trace, "record_prediction_resolved", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("trace"))
    )
    resolver._resolve_due_predictions(subnets=[])
    assert _row_on_disk(ledger, "r1")["side_effect_warnings"] == ["record_prediction_resolved"]
    assert _markers(ledger)["r1"]["pending"] == ["finalize"]

    monkeypatch.setattr(expired_recovery, "write_effect_receipt", real_write)
    monkeypatch.setattr(expired_recovery, "_mark_effect_indeterminate", real_mark)
    monkeypatch.setattr(prediction_trace, "record_prediction_resolved", real_trace)
    expired_recovery.recover_expired_predictions()

    assert _markers(ledger)["r1"]["pending"] == []
    assert "side_effect_warnings" not in _row_on_disk(ledger, "r1")


def test_a_stamping_write_that_fails_once_is_retried(ledger, sinks, monkeypatch):
    from internal.council import prediction_trace

    real_move = expired_recovery.move_effects_on_ledger
    calls = {"n": 0}

    def fails_once(pairs, warnings=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("ledger busy")
        return real_move(pairs, warnings=warnings)

    monkeypatch.setattr(
        prediction_trace, "record_prediction_resolved", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("trace"))
    )
    monkeypatch.setattr(expired_recovery, "move_effects_on_ledger", fails_once)
    resolver._resolve_due_predictions(subnets=[])

    assert _row_on_disk(ledger, "r1").get("side_effect_warnings") == ["record_prediction_resolved"]
    assert _markers(ledger)["r1"]["pending"] == []


def test_every_warning_the_finalize_reported_is_stamped_not_just_the_first(ledger, sinks, monkeypatch):
    from internal.council import prediction_trace

    def fails(*_a, **_kw):
        raise RuntimeError("sink down")

    monkeypatch.setattr(prediction_trace, "record_prediction_resolved", fails)
    monkeypatch.setattr(trail_events, "emit_prediction_resolved", fails)
    resolver._resolve_due_predictions(subnets=[])

    assert _row_on_disk(ledger, "r1")["side_effect_warnings"] == [
        "record_prediction_resolved",
        "emit_prediction_resolved",
    ]


def test_a_warning_on_the_second_row_lands_on_the_second_row(ledger, sinks, monkeypatch):
    from internal.council import prediction_trace

    real = prediction_trace.record_prediction_resolved

    def trace_fails_for_r2(prediction, *a, **k):
        if prediction.get("id") == "r2":
            raise RuntimeError("trace")
        return real(prediction, *a, **k)

    monkeypatch.setattr(prediction_trace, "record_prediction_resolved", trace_fails_for_r2)
    _two_rows(ledger)
    resolver._resolve_due_predictions(subnets=[])

    assert "side_effect_warnings" not in _row_on_disk(ledger, "r1")
    assert _row_on_disk(ledger, "r2").get("side_effect_warnings") == ["record_prediction_resolved"]


def test_stamping_warnings_adds_no_ledger_write(ledger, sinks, monkeypatch):
    import os

    from internal.council import prediction_trace

    writes = {"n": 0}
    real_replace = os.replace

    def counting_replace(src, dst, *a, **k):
        if str(dst) == str(ledger):
            writes["n"] += 1
        return real_replace(src, dst, *a, **k)

    monkeypatch.setattr(os, "replace", counting_replace)
    resolver._resolve_due_predictions(subnets=[])
    clean_writes = writes["n"]

    disk = json.loads(ledger.read_text())
    disk["predictions"] = [_second_due_row()]
    ledger.write_text(json.dumps(disk))
    monkeypatch.setattr(
        prediction_trace, "record_prediction_resolved", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("trace"))
    )
    writes["n"] = 0
    resolver._resolve_due_predictions(subnets=[])

    assert writes["n"] == clean_writes, (writes["n"], clean_writes)


def test_a_replay_that_ran_no_finalize_because_of_a_revoke_keeps_the_stamped_warning(ledger, sinks, monkeypatch):
    from internal.council import prediction_trace

    real_write = expired_recovery.write_effect_receipt
    real_mark = expired_recovery._mark_effect_indeterminate

    def io_error(*_a, **_kw):
        raise OSError(errno.EIO, "input/output error")

    monkeypatch.setattr(
        expired_recovery,
        "write_effect_receipt",
        lambda key, effect: io_error() if effect == "finalize" else real_write(key, effect),
    )
    monkeypatch.setattr(expired_recovery, "_mark_effect_indeterminate", io_error)
    monkeypatch.setattr(
        prediction_trace, "record_prediction_resolved", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("trace"))
    )
    resolver._resolve_due_predictions(subnets=[])
    assert _row_on_disk(ledger, "r1")["side_effect_warnings"] == ["record_prediction_resolved"]
    assert _markers(ledger)["r1"]["pending"] == ["finalize"]

    monkeypatch.setattr(expired_recovery, "write_effect_receipt", real_write)
    monkeypatch.setattr(expired_recovery, "_mark_effect_indeterminate", real_mark)
    monkeypatch.setattr(resolver, "_cycle_writes_revoked_safe", lambda: True)
    expired_recovery.recover_expired_predictions()

    assert _row_on_disk(ledger, "r1").get("side_effect_warnings") == ["record_prediction_resolved"], (
        "a replay that ran no finalize sink has no evidence to replace the stamp with"
    )


def _io_error(*_a, **_kw):
    raise OSError(errno.EIO, "input/output error")


def _receipt_fails_for(monkeypatch, wanted):
    """wanted: set of (row_id, effect). Receipt write and indeterminate mark both fail for them."""
    real_write = expired_recovery.write_effect_receipt
    real_mark = expired_recovery._mark_effect_indeterminate

    def write(key, effect):
        if (key[1], effect) in wanted:
            _io_error()
        return real_write(key, effect)

    def mark(row, effect):
        if (row.get("id"), effect) in wanted:
            _io_error()
        return real_mark(row, effect)

    monkeypatch.setattr(expired_recovery, "write_effect_receipt", write)
    monkeypatch.setattr(expired_recovery, "_mark_effect_indeterminate", mark)
    return real_write, real_mark


def _trace_fails_for(monkeypatch, ids):
    real = prediction_trace.record_prediction_resolved

    def trace(prediction, *a, **k):
        if prediction.get("id") in ids:
            raise RuntimeError("trace")
        return real(prediction, *a, **k)

    monkeypatch.setattr(prediction_trace, "record_prediction_resolved", trace)
    return real


def test_sweep_moving_a_non_finalize_effect_keeps_the_flush_stamp(ledger, sinks, monkeypatch):
    """Finalize was receipted with a trace warning; only 'signal' is left for the sweep.
    The sweep's signal move passes no warnings, so the stamp must stay."""
    real_write, real_mark = _receipt_fails_for(monkeypatch, {("r1", "signal")})
    real_trace = _trace_fails_for(monkeypatch, {"r1"})
    resolver._resolve_due_predictions(subnets=[])
    assert _markers(ledger)["r1"]["pending"] == ["signal"]
    assert _row_on_disk(ledger, "r1")["side_effect_warnings"] == ["record_prediction_resolved"]

    monkeypatch.setattr(expired_recovery, "write_effect_receipt", real_write)
    monkeypatch.setattr(expired_recovery, "_mark_effect_indeterminate", real_mark)
    monkeypatch.setattr(prediction_trace, "record_prediction_resolved", real_trace)
    expired_recovery.recover_expired_predictions()

    assert _markers(ledger)["r1"]["pending"] == []
    assert _row_on_disk(ledger, "r1").get("side_effect_warnings") == ["record_prediction_resolved"]


def test_a_replay_warning_on_one_row_is_not_stamped_on_the_next_row(ledger, sinks, monkeypatch):
    """r1 replays finalize and its trace fails again; r2 only replays 'signal'. r2 stays clean."""
    _two_rows(ledger)
    real_write, real_mark = _receipt_fails_for(monkeypatch, {("r1", "finalize"), ("r2", "signal")})
    resolver._resolve_due_predictions(subnets=[])
    assert _markers(ledger)["r1"]["pending"] == ["finalize"]
    assert _markers(ledger)["r2"]["pending"] == ["signal"]
    assert "side_effect_warnings" not in _row_on_disk(ledger, "r2")

    monkeypatch.setattr(expired_recovery, "write_effect_receipt", real_write)
    monkeypatch.setattr(expired_recovery, "_mark_effect_indeterminate", real_mark)
    _trace_fails_for(monkeypatch, {"r1"})
    expired_recovery.recover_expired_predictions()

    assert _markers(ledger)["r1"]["pending"] == []
    assert _markers(ledger)["r2"]["pending"] == []
    assert _row_on_disk(ledger, "r1").get("side_effect_warnings") == ["record_prediction_resolved"]
    assert "side_effect_warnings" not in _row_on_disk(ledger, "r2")


def test_a_stamp_that_always_fails_is_tried_exactly_twice_and_logged_once(ledger, sinks, monkeypatch, caplog):
    calls = {"n": 0}

    def always_fails(pairs, warnings=None):
        calls["n"] += 1
        raise RuntimeError("ledger busy")

    monkeypatch.setattr(expired_recovery, "move_effects_on_ledger", always_fails)
    with caplog.at_level(logging.ERROR, logger="internal.council.resolver"):
        resolver._resolve_due_predictions(subnets=[])

    msgs = [r.getMessage() for r in caplog.records if "learning markers not cleared" in r.getMessage()]
    assert calls["n"] == 2, calls
    assert len(msgs) == 1, msgs


def test_a_replay_that_reports_portfolios_unobservable_keeps_finalize_pending(ledger, sinks, monkeypatch):
    real_write, real_mark = _receipt_fails_for(monkeypatch, {("r1", "finalize")})
    resolver._resolve_due_predictions(subnets=[])
    assert _markers(ledger)["r1"]["pending"] == ["finalize"]

    monkeypatch.setattr(expired_recovery, "write_effect_receipt", real_write)
    monkeypatch.setattr(expired_recovery, "_mark_effect_indeterminate", real_mark)
    monkeypatch.setattr(resolver, "on_prediction_resolved", lambda *a, **k: {"portfolios_unobservable": True})
    result = expired_recovery.recover_expired_predictions()

    assert result.get("ok") is False, result
    assert "finalize" in _markers(ledger)["r1"]["pending"]


def test_an_indeterminate_finalize_settled_by_the_sweep_keeps_the_flush_stamp(ledger, sinks, monkeypatch):
    """Finalize ran with a trace warning; its receipt failed but the indeterminate mark landed.
    The sweep settles it without replaying, so the stamp the flush wrote stays."""
    real_write = expired_recovery.write_effect_receipt

    def write(key, effect):
        if effect == "finalize":
            _io_error()
        return real_write(key, effect)

    monkeypatch.setattr(expired_recovery, "write_effect_receipt", write)
    real_trace = _trace_fails_for(monkeypatch, {"r1"})
    resolver._resolve_due_predictions(subnets=[])
    assert _markers(ledger)["r1"]["indeterminate"] == ["finalize"], _markers(ledger)["r1"]
    assert _row_on_disk(ledger, "r1")["side_effect_warnings"] == ["record_prediction_resolved"]

    monkeypatch.setattr(expired_recovery, "write_effect_receipt", real_write)
    monkeypatch.setattr(prediction_trace, "record_prediction_resolved", real_trace)
    expired_recovery.recover_expired_predictions()

    assert _markers(ledger)["r1"]["indeterminate"] == []
    assert _row_on_disk(ledger, "r1").get("side_effect_warnings") == ["record_prediction_resolved"]


def _conflicting_on_r1(monkeypatch, ledger_path, times):
    """Edit r1 on disk after the stamping write has read the ledger, so r1 conflicts.

    times is how many of the stamping writes conflict. r2, in the same write, still commits.
    """
    real = predictions_store.merge_ledger_changes
    calls = {"n": 0}

    def merge(before, after, **kwargs):
        if kwargs.get("trigger") == "learning_effect_receipt" and not calls.get("stop"):
            calls["n"] += 1
            if calls["n"] <= times:
                disk = json.loads(ledger_path.read_text())
                for row in disk["resolved"]:
                    if row["id"] == "r1":
                        row["note"] = f"concurrent edit {calls['n']}"
                ledger_path.write_text(json.dumps(disk))
        return real(before, after, **kwargs)

    monkeypatch.setattr(predictions_store, "merge_ledger_changes", merge)
    return calls


def test_a_stamp_that_conflicts_on_one_row_while_another_row_commits_is_retried(ledger, sinks, monkeypatch):
    from internal.council import prediction_trace

    real_trace = prediction_trace.record_prediction_resolved
    monkeypatch.setattr(
        prediction_trace,
        "record_prediction_resolved",
        lambda p, *a, **k: (_ for _ in ()).throw(RuntimeError("trace")) if p.get("id") == "r1" else real_trace(p, *a, **k),
    )
    _two_rows(ledger)
    calls = _conflicting_on_r1(monkeypatch, ledger, times=1)

    resolver._resolve_due_predictions(subnets=[])

    assert calls["n"] == 2, "the first stamping write conflicted on r1, so it must be retried once"
    assert _row_on_disk(ledger, "r1").get("side_effect_warnings") == ["record_prediction_resolved"]
    assert _markers(ledger)["r1"]["pending"] == []
    assert _markers(ledger)["r2"]["pending"] == []


def test_a_stamp_that_conflicts_on_every_attempt_does_not_raise_and_the_sweep_settles_the_markers(
    ledger, sinks, monkeypatch
):
    from internal.council import prediction_trace

    real_trace = prediction_trace.record_prediction_resolved
    monkeypatch.setattr(
        prediction_trace,
        "record_prediction_resolved",
        lambda p, *a, **k: (_ for _ in ()).throw(RuntimeError("trace")) if p.get("id") == "r1" else real_trace(p, *a, **k),
    )
    _two_rows(ledger)
    calls = _conflicting_on_r1(monkeypatch, ledger, times=99)

    resolver._resolve_due_predictions(subnets=[])

    assert calls["n"] >= 2, "the conflicting write was retried at least once"
    assert _markers(ledger)["r1"]["pending"], "r1's markers stay for the sweep"
    assert _markers(ledger)["r2"]["pending"] == []

    calls["stop"] = True
    expired_recovery.recover_expired_predictions()

    assert _row_on_disk(ledger, "r1").get("side_effect_warnings") == ["record_prediction_resolved"], (
        "the sweep settles r1 from its receipt and must still stamp the warning the flush reported"
    )
    assert _markers(ledger)["r1"]["pending"] == []
    expected = _once(rows=2)
    expected["trace_resolved"] = 1  # r1's trace write is the one that failed
    assert _counts(sinks) == expected, "the sweep must settle r1 from its receipts, not run it again"


def _stale_close_stamp_with_finalize_pending(ledger, monkeypatch):
    close_calls = []

    def close_fails(*_a, **_kw):
        close_calls.append(1)
        raise RuntimeError("portfolio write busy")

    real_write = expired_recovery.write_effect_receipt

    def finalize_receipt_fails(key, effect):
        if effect == "finalize":
            raise OSError(errno.EIO, "input/output error")
        return real_write(key, effect)

    monkeypatch.setattr(resolver, "on_prediction_resolved", close_fails)
    monkeypatch.setattr(expired_recovery, "write_effect_receipt", finalize_receipt_fails)
    monkeypatch.setattr(
        expired_recovery, "_mark_effect_indeterminate", lambda *a, **k: (_ for _ in ()).throw(OSError(errno.EIO, "io"))
    )
    resolver._resolve_due_predictions(subnets=[])
    assert "on_prediction_resolved" in _row_on_disk(ledger, "r1")["side_effect_warnings"]
    monkeypatch.setattr(expired_recovery, "write_effect_receipt", real_write)


def test_a_revoke_that_lands_after_finalize_returns_keeps_the_stamp(ledger, sinks, monkeypatch):
    """A revoke seen at any point of the replay means the sinks that ran are unknown, so the
    stamp stays. Erasing the only record of a failure is worse than keeping a stale one."""
    from internal.judges import tracker

    _stale_close_stamp_with_finalize_pending(ledger, monkeypatch)
    monkeypatch.setattr(resolver, "on_prediction_resolved", tracker.on_prediction_resolved)
    real_finalize = resolver.atomic_finalize_resolution
    revoked = {"on": False}

    def finalize_then_revoke(*a, **k):
        result = real_finalize(*a, **k)
        revoked["on"] = True
        return result

    monkeypatch.setattr(resolver, "atomic_finalize_resolution", finalize_then_revoke)
    monkeypatch.setattr(resolver, "_cycle_writes_revoked_safe", lambda: revoked["on"])
    expired_recovery.recover_expired_predictions()

    assert revoked["on"], "the replay never ran, so this test would prove nothing"
    assert "on_prediction_resolved" in _row_on_disk(ledger, "r1").get("side_effect_warnings", [])


def test_a_revoke_that_lands_in_the_middle_of_the_replay_keeps_the_stamp(ledger, sinks, monkeypatch):
    """The first sink flips the revoke on, so the later sinks (trace, trail) are skipped and the
    replay reports no warnings. That silence is not evidence, so the stamp stays."""
    from internal.council import prediction_trace
    from internal.judges import tracker

    real_trace = prediction_trace.record_prediction_resolved
    monkeypatch.setattr(
        prediction_trace, "record_prediction_resolved", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("trace"))
    )
    real_write = expired_recovery.write_effect_receipt
    monkeypatch.setattr(
        expired_recovery,
        "write_effect_receipt",
        lambda key, effect: (_ for _ in ()).throw(OSError(errno.EIO, "io")) if effect == "finalize" else real_write(key, effect),
    )
    monkeypatch.setattr(
        expired_recovery, "_mark_effect_indeterminate", lambda *a, **k: (_ for _ in ()).throw(OSError(errno.EIO, "io"))
    )
    resolver._resolve_due_predictions(subnets=[])
    assert _row_on_disk(ledger, "r1")["side_effect_warnings"] == ["record_prediction_resolved"]

    monkeypatch.setattr(expired_recovery, "write_effect_receipt", real_write)
    monkeypatch.setattr(prediction_trace, "record_prediction_resolved", real_trace)
    revoked = {"on": False}

    def close_then_revoke(*a, **k):
        revoked["on"] = True
        return tracker.on_prediction_resolved(*a, **k)

    monkeypatch.setattr(resolver, "on_prediction_resolved", close_then_revoke)
    monkeypatch.setattr(resolver, "_cycle_writes_revoked_safe", lambda: revoked["on"])
    expired_recovery.recover_expired_predictions()

    assert _row_on_disk(ledger, "r1").get("side_effect_warnings") == ["record_prediction_resolved"]



def _flush_leaves_finalize_pending_with_stamp(ledger, monkeypatch):
    from internal.council import prediction_trace

    real_write = expired_recovery.write_effect_receipt
    real_mark = expired_recovery._mark_effect_indeterminate

    def io_error(*_a, **_kw):
        raise OSError(errno.EIO, "input/output error")

    monkeypatch.setattr(
        expired_recovery,
        "write_effect_receipt",
        lambda key, effect: io_error() if effect == "finalize" else real_write(key, effect),
    )
    monkeypatch.setattr(expired_recovery, "_mark_effect_indeterminate", io_error)
    monkeypatch.setattr(
        prediction_trace, "record_prediction_resolved", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("trace"))
    )
    resolver._resolve_due_predictions(subnets=[])
    assert _row_on_disk(ledger, "r1")["side_effect_warnings"] == ["record_prediction_resolved"]
    assert _markers(ledger)["r1"]["pending"] == ["finalize"]
    monkeypatch.setattr(expired_recovery, "write_effect_receipt", real_write)
    monkeypatch.setattr(expired_recovery, "_mark_effect_indeterminate", real_mark)


def test_a_revoke_that_lands_after_the_sweep_started_and_before_the_replay_keeps_the_stamp(
    ledger, sinks, monkeypatch
):
    _flush_leaves_finalize_pending_with_stamp(ledger, monkeypatch)
    revoked = {"on": False}
    real_state = expired_recovery._ledger_effect_state

    def state_then_revoke(key, effect):
        revoked["on"] = True
        return real_state(key, effect)

    monkeypatch.setattr(expired_recovery, "_ledger_effect_state", state_then_revoke)
    monkeypatch.setattr(resolver, "_cycle_writes_revoked_safe", lambda: revoked["on"])
    expired_recovery.recover_expired_predictions()

    assert revoked["on"], "the sweep never reached the replay, so this test would prove nothing"
    assert _row_on_disk(ledger, "r1").get("side_effect_warnings") == ["record_prediction_resolved"]


def test_a_revoke_keeps_the_stamp_for_a_marker_without_the_live_flag(ledger, sinks, monkeypatch):
    _flush_leaves_finalize_pending_with_stamp(ledger, monkeypatch)
    disk = json.loads(ledger.read_text())
    for row in disk["resolved"]:
        if row["id"] == "r1":
            row["learning_effects"].pop("live", None)
            row["learning_effects"].pop("judge_nudge", None)
    ledger.write_text(json.dumps(disk))
    monkeypatch.setattr(resolver, "_cycle_writes_revoked_safe", lambda: True)
    expired_recovery.recover_expired_predictions()

    assert _row_on_disk(ledger, "r1").get("side_effect_warnings") == ["record_prediction_resolved"]


def test_a_retry_that_succeeds_logs_no_failure(ledger, sinks, monkeypatch, caplog):
    from internal.council import prediction_trace

    real_trace = prediction_trace.record_prediction_resolved
    monkeypatch.setattr(
        prediction_trace,
        "record_prediction_resolved",
        lambda p, *a, **k: (_ for _ in ()).throw(RuntimeError("trace")) if p.get("id") == "r1" else real_trace(p, *a, **k),
    )
    _two_rows(ledger)
    _conflicting_on_r1(monkeypatch, ledger, times=1)
    with caplog.at_level(logging.ERROR, logger="internal.council.resolver"):
        resolver._resolve_due_predictions(subnets=[])

    assert _row_on_disk(ledger, "r1").get("side_effect_warnings") == ["record_prediction_resolved"]
    assert _markers(ledger)["r1"]["pending"] == [] and _markers(ledger)["r2"]["pending"] == []
    assert [r.getMessage() for r in caplog.records if "markers not cleared" in r.getMessage()] == []


def test_a_crash_after_the_finalize_receipt_still_leaves_the_warning_on_the_row(ledger, sinks, monkeypatch):
    """The process dies after the receipt is written and before the stamping write."""
    from internal.council import prediction_trace

    monkeypatch.setattr(
        prediction_trace,
        "record_prediction_resolved",
        lambda *_a, **_kw: (_ for _ in ()).throw(RuntimeError("trace disk unavailable")),
    )

    def crash(*_a, **_kw):
        raise SystemExit("process died before the markers were cleared")

    real_move = expired_recovery.move_effects_on_ledger
    monkeypatch.setattr(expired_recovery, "move_effects_on_ledger", crash)
    try:
        resolver._resolve_due_predictions(subnets=[])
    except SystemExit:
        pass
    monkeypatch.setattr(expired_recovery, "move_effects_on_ledger", real_move)

    assert "side_effect_warnings" not in _row_on_disk(ledger, "r1")
    expired_recovery.recover_expired_predictions()

    assert _row_on_disk(ledger, "r1").get("side_effect_warnings") == ["record_prediction_resolved"]
    assert _markers(ledger)["r1"]["pending"] == []


def test_a_sweep_replay_that_reports_a_warning_stamps_it_even_if_the_stamp_is_lost(ledger, sinks, monkeypatch):
    """The sweep replays finalize, writes the receipt, and fails its own ledger stamp once."""
    from internal.council import prediction_trace

    real_flush = resolver._flush_deferred_learning
    _crash_at_flush(monkeypatch)
    with pytest.raises(ProcessDied):
        resolver._resolve_due_predictions(subnets=[])
    monkeypatch.setattr(resolver, "_flush_deferred_learning", real_flush)
    monkeypatch.setattr(
        prediction_trace,
        "record_prediction_resolved",
        lambda *_a, **_kw: (_ for _ in ()).throw(RuntimeError("trace disk unavailable")),
    )
    real_move = expired_recovery._move_effect_on_ledger
    state = {"failed": False}

    def move(row, effect, warnings=None):
        if effect == "finalize" and not state["failed"]:
            state["failed"] = True
            raise OSError("ledger write failed after the receipt")
        return real_move(row, effect, warnings=warnings)

    monkeypatch.setattr(expired_recovery, "_move_effect_on_ledger", move)
    try:
        expired_recovery.recover_expired_predictions()
    except Exception:
        pass
    assert state["failed"], "the replay must have reached its stamp"
    expired_recovery.recover_expired_predictions()

    assert _row_on_disk(ledger, "r1").get("side_effect_warnings") == ["record_prediction_resolved"]


def test_warnings_kept_for_a_receipt_are_replaced_and_cleared_by_a_later_replay():
    key = ("id", "r9")
    expired_recovery.record_effect_warnings(key, "finalize", ["record_prediction_resolved"])
    assert expired_recovery.get_receipt_warnings(key, "finalize") == ["record_prediction_resolved"]
    expired_recovery.record_effect_warnings(key, "finalize", ["pick_history_finalize"])
    assert expired_recovery.get_receipt_warnings(key, "finalize") == ["pick_history_finalize"]
    expired_recovery.record_effect_warnings(key, "finalize", [])
    assert expired_recovery.get_receipt_warnings(key, "finalize") is None
    assert not expired_recovery.has_effect_receipt(key, "finalize"), "warnings are not a receipt"


def test_a_stamp_that_conflicts_on_a_row_with_only_a_marker_to_clear_is_retried(ledger, sinks, monkeypatch):
    _two_rows(ledger)
    calls = _conflicting_on_r1(monkeypatch, ledger, times=1)

    resolver._resolve_due_predictions(subnets=[])

    assert calls["n"] == 2, "r1 has markers but no warning, and its conflict must still trigger the retry"
    assert _markers(ledger)["r1"]["pending"] == [] and _markers(ledger)["r2"]["pending"] == []


def test_a_stamp_that_conflicts_on_a_row_with_only_a_warning_to_stamp_is_retried(ledger, sinks, monkeypatch):
    """Every receipt and indeterminate mark fails for r1, so r1 has a warning and no marker move."""
    _two_rows(ledger)
    _trace_fails_for(monkeypatch, {"r1"})
    _receipt_fails_for(monkeypatch, {("r1", name) for name in ("expert", "impact", "finalize", "scenario", "signal")})
    calls = _conflicting_on_r1(monkeypatch, ledger, times=1)

    resolver._resolve_due_predictions(subnets=[])

    assert calls["n"] == 2, "r1 has a warning but no marker pair, and its conflict must still trigger the retry"
    assert _row_on_disk(ledger, "r1").get("side_effect_warnings") == ["record_prediction_resolved"]


@pytest.mark.parametrize("error", ["lock_timeout", "unreadable"])
def test_a_journal_failure_while_reading_stored_warnings_does_not_abort_the_sweep(
    ledger, sinks, monkeypatch, error
):
    """Receipts exist and the markers are pending. Reading the stored warnings then fails."""

    def clear_fails(_pairs, warnings=None):
        raise RuntimeError("ledger busy")

    real_clear = expired_recovery.move_effects_on_ledger
    monkeypatch.setattr(expired_recovery, "move_effects_on_ledger", clear_fails)
    resolver._resolve_due_predictions(subnets=[])
    monkeypatch.setattr(expired_recovery, "move_effects_on_ledger", real_clear)
    assert _markers(ledger)["r1"]["pending"], "the clear failed, so the markers stay"

    failure = (
        expired_recovery.LearningEffectReceiptsLockTimeout("held")
        if error == "lock_timeout"
        else expired_recovery.LearningEffectReceiptsUnreadable("damaged")
    )

    def read_fails(*_a, **_kw):
        raise failure

    real_read = expired_recovery.get_receipt_warnings
    monkeypatch.setattr(expired_recovery, "get_receipt_warnings", read_fails)
    result = expired_recovery.recover_expired_predictions()

    assert result is not None
    assert _counts(sinks) == _once(), "no effect may run again"
    assert _markers(ledger)["r1"]["pending"], "the marker stays for a later sweep"

    monkeypatch.setattr(expired_recovery, "get_receipt_warnings", real_read)
    expired_recovery.recover_expired_predictions()
    assert _markers(ledger)["r1"]["pending"] == []


def test_one_unreadable_read_of_stored_warnings_does_not_stop_the_sweep_settling_the_next_row(
    ledger, sinks, monkeypatch
):
    _two_rows(ledger)

    def clear_fails(_pairs, warnings=None):
        raise RuntimeError("ledger busy")

    real_clear = expired_recovery.move_effects_on_ledger
    monkeypatch.setattr(expired_recovery, "move_effects_on_ledger", clear_fails)
    resolver._resolve_due_predictions(subnets=[])
    monkeypatch.setattr(expired_recovery, "move_effects_on_ledger", real_clear)

    real_read = expired_recovery.get_receipt_warnings
    calls = {"n": 0}

    def first_read_fails(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise expired_recovery.LearningEffectReceiptsUnreadable("damaged once")
        return real_read(*args, **kwargs)

    monkeypatch.setattr(expired_recovery, "get_receipt_warnings", first_read_fails)
    expired_recovery.recover_expired_predictions()

    assert _markers(ledger)["r2"]["pending"] == [], "the failed read on r1 must not stop r2 settling"
    assert _counts(sinks) == _once(rows=2)


def test_a_journal_that_turns_unreadable_after_the_sweep_applied_an_effect_is_not_repeated_by_the_flush(
    ledger, sinks, monkeypatch, tmp_path
):
    """The sweep settled r1 and cleared its markers. Outside damage then corrupts the journal."""
    real_flush = resolver._flush_deferred_learning

    def flush_after_the_sweep(deferral, commit_result):
        expired_recovery.recover_expired_predictions()
        (tmp_path / "learning_effect_receipts.json").write_text("not json {")
        real_flush(deferral, commit_result)

    monkeypatch.setattr(resolver, "_flush_deferred_learning", flush_after_the_sweep)
    resolver._resolve_due_predictions(subnets=[])

    assert _counts(sinks) == _once(), _counts(sinks)


def test_an_unreadable_journal_with_an_unreadable_ledger_state_still_runs_the_effect_live(
    ledger, sinks, monkeypatch, tmp_path
):
    (tmp_path / "learning_effect_receipts.json").write_text("not json {")

    def ledger_state_unreadable(*_a, **_kw):
        raise RuntimeError("ledger unreadable")

    monkeypatch.setattr(expired_recovery, "_ledger_effect_state", ledger_state_unreadable)
    resolver._resolve_due_predictions(subnets=[])

    assert _counts(sinks) == _once(), "today's behavior is kept when the ledger cannot say either"


def test_an_effect_already_marked_indeterminate_is_not_run_by_a_flush_that_finds_the_journal_unreadable(
    ledger, sinks, monkeypatch, tmp_path
):
    real_flush = resolver._flush_deferred_learning

    def flush_after_marking(deferral, commit_result):
        for _key, name, _effect, prediction in deferral.items:
            expired_recovery._mark_effect_indeterminate(prediction, name)
        (tmp_path / "learning_effect_receipts.json").write_text("not json {")
        real_flush(deferral, commit_result)

    monkeypatch.setattr(resolver, "_flush_deferred_learning", flush_after_marking)
    resolver._resolve_due_predictions(subnets=[])

    assert _counts(sinks) == {name: 0 for name in SINKS}, _counts(sinks)
