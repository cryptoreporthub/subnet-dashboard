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
