"""Learning effects for a resolved row run only after its ledger save succeeds.

Before the fix, resolve_prediction_at_horizon runs learning per row, and the ledger
save runs once after the loop. A refused save leaves the learning applied, and the
next cycle grades the same row again.

These tests observe the write sinks themselves, not the helper functions, and force
learning on so every sink is reachable.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone

import pytest

from internal.council import pick_history, prediction_trace, resolver, scenario_memory
from internal.council import weights
from internal.learning import trail_bus, trail_events


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
    monkeypatch.setattr(resolver, "fetch_prices", lambda _subnets=None: {})
    monkeypatch.setattr(resolver, "hydrate_candles_for_netuid", lambda *_a, **_kw: False)
    monkeypatch.setattr(
        resolver,
        "lookup_horizon_price",
        lambda *_a, **_kw: ("ok", 12.0, {"price_source": "test", "price_lag_seconds": 0}),
    )
    monkeypatch.setattr(resolver, "_skip_council_learning", lambda _prediction: False)
    monkeypatch.setattr(resolver, "_cycle_writes_revoked_safe", lambda: False)
    # The expert nudge fires only for council-published rows whose replay expert matches.
    from internal.council import signal_expert
    from internal.learning import evidence

    monkeypatch.setattr(evidence, "evidence_population", lambda _row: "council_published")
    monkeypatch.setattr(signal_expert, "expert_for_replay_row", lambda _row: "oracle")
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


def _sink_calls(calls):
    return [name for name in calls if name in SINKS]


def test_refused_ledger_commit_runs_no_learning(ledger, sinks, monkeypatch):
    before = ledger.read_bytes()
    real_replace = os.replace

    def refuse_ledger_write(src, dst):
        if str(dst) == str(ledger):
            raise OSError("injected ledger failure")
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", refuse_ledger_write)
    try:
        resolver._resolve_due_predictions(subnets=[])
    except Exception:
        pass

    assert _sink_calls(sinks) == [], f"learning ran before the commit: {sinks}"
    assert ledger.read_bytes() == before


def test_successful_commit_runs_each_sink_exactly_once(ledger, sinks):
    resolver._resolve_due_predictions(subnets=[])

    counts = {name: sinks.count(name) for name in SINKS}
    assert counts == {name: 1 for name in SINKS}, counts


def test_conflicted_row_runs_no_learning(ledger, sinks, monkeypatch):
    real_commit = resolver._commit_ledger_changes

    def other_writer_then_commit(before, after, **kwargs):
        # Another writer changes r1 on disk after the cycle read it, so the merge
        # reports a conflict for r1 and does not apply the resolution.
        disk = json.loads(ledger.read_text())
        for row in disk["predictions"]:
            if row.get("id") == "r1":
                row["note"] = "other writer"
        ledger.write_text(json.dumps(disk))
        return real_commit(before, after, **kwargs)

    monkeypatch.setattr(resolver, "_commit_ledger_changes", other_writer_then_commit)
    resolver._resolve_due_predictions(subnets=[])

    disk = json.loads(ledger.read_text())
    assert [r.get("status") for r in disk["predictions"] if r.get("id") == "r1"] == ["pending"]
    assert _sink_calls(sinks) == [], f"learning ran for a conflicted row: {sinks}"


def test_impact_env_override_still_stamps_the_row_before_save(monkeypatch):
    """With IMPACT_STRENGTH set, the saved row must still carry impact_strength_after."""
    monkeypatch.setenv("IMPACT_STRENGTH", "1.5")
    row = _due_row()
    resolver._stage_impact_strength(row, True, resolver._LearningDeferral())
    assert row["impact_strength_after"] == 1.5


def test_impact_staging_error_skips_only_that_row(monkeypatch):
    """A failure while staging must not abort the cycle, and must queue nothing for the row."""
    def boom(*_a, **_kw):
        raise RuntimeError("soul map unreadable")

    monkeypatch.setattr(resolver, "_stage_impact_strength", boom)
    deferral = resolver._LearningDeferral()
    token = resolver._learning_deferral.set(deferral)
    try:
        resolver._stage_or_run_impact(_due_row(), True)
    finally:
        resolver._learning_deferral.reset(token)
    assert deferral.items == []


def test_late_grade_that_raises_queues_no_learning(ledger, sinks, monkeypatch):
    """A row past grace whose late grade raises is expired. Its queued learning is dropped."""
    now = datetime.now(timezone.utc)
    old = now - timedelta(days=60)
    disk = json.loads(ledger.read_text())
    disk["predictions"][0]["resolve_at"] = old.isoformat().replace("+00:00", "Z")
    disk["predictions"][0]["predicted_at"] = (old - timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    disk["predictions"][0]["resolve_attempts"] = 99
    disk["predictions"][0]["horizon_hours"] = 1
    ledger.write_text(json.dumps(disk))

    def raise_in_late_grade(*_a, **_kw):
        raise RuntimeError("snapshot failed during late grade")

    monkeypatch.setattr(resolver, "_ensure_subnet_snapshot", raise_in_late_grade)
    resolver._resolve_due_predictions(subnets=[])

    rows = json.loads(ledger.read_text())
    assert [r["status"] for r in rows["resolved"] if r.get("id") == "r1"] == ["expired"]
    assert _sink_calls(sinks) == [], f"learning ran for an expired row: {sinks}"


def test_skipped_first_same_tier_row_logs_staged_vs_applied_impact(tmp_path, monkeypatch, caplog):
    """Row 2 stages from row 1's delta. If row 1 is skipped, the saved copy drifts from
    what the soul map applied. That drift must be logged, and the trail must carry the
    applied value, which matches the soul map.
    """
    import logging

    from internal.council import pick_history, prediction_trace, resolver, scenario_memory, weights
    from internal.learning import trail_events

    now = datetime.now(timezone.utc)
    stamp = (now - timedelta(seconds=60)).isoformat().replace("+00:00", "Z")
    pred_stamp = (now - timedelta(hours=1)).isoformat().replace("+00:00", "Z")

    def due_small(row_id, pct):
        row = _due_row(row_id)
        # Distinct predicted_pct: the resolver dedupes same-netuid, same-pct rows in one window.
        row["predicted_pct"] = pct
        row["market_impact"] = {"tier": "small"}
        row["resolve_at"] = stamp
        row["predicted_at"] = pred_stamp
        row["reference_price"] = 10.0
        return row

    path = tmp_path / "predictions.json"
    path.write_text(json.dumps({"predictions": [due_small("r1", 5.0), due_small("r2", 6.0)], "resolved": [], "stats": {}}))
    monkeypatch.setattr(resolver, "PREDICTIONS_PATH", str(path))
    monkeypatch.setattr(resolver, "fetch_prices", lambda _subnets=None: {})
    monkeypatch.setattr(resolver, "hydrate_candles_for_netuid", lambda *_a, **_kw: False)
    monkeypatch.setattr(
        resolver, "lookup_horizon_price",
        lambda *_a, **_kw: ("ok", 12.0, {"price_source": "test", "price_lag_seconds": 0}),
    )
    monkeypatch.setattr(resolver, "_skip_council_learning", lambda _p: False)
    monkeypatch.setattr(resolver, "_cycle_writes_revoked_safe", lambda: False)
    monkeypatch.setattr(weights, "SOUL_MAP_PATH", str(tmp_path / "soul_map.json"))
    monkeypatch.delenv("IMPACT_STRENGTH", raising=False)
    # Silence every effect except the impact write, which is the one under test.
    for target, name in (
        (weights, "nudge_expert"), (resolver, "nudge_signal_weight"),
        (resolver, "on_prediction_resolved"), (prediction_trace, "record_prediction_resolved"),
        (pick_history, "finalize_from_prediction"), (scenario_memory, "record_outcome"),
    ):
        monkeypatch.setattr(target, name, lambda *_a, **_kw: None)
    trail_seen = {}

    def record_trail(prediction, *_a, **_kw):
        trail_seen[prediction.get("id")] = prediction.get("impact_strength_after")

    monkeypatch.setattr(trail_events, "emit_prediction_resolved", record_trail)

    real_commit = resolver._commit_ledger_changes

    def other_writer_then_commit(before, after, **kwargs):
        disk = json.loads(path.read_text())
        for row in disk["predictions"]:
            if row.get("id") == "r1":
                row["note"] = "other writer"
        path.write_text(json.dumps(disk))
        return real_commit(before, after, **kwargs)

    monkeypatch.setattr(resolver, "_commit_ledger_changes", other_writer_then_commit)
    with caplog.at_level(logging.WARNING):
        resolver._resolve_due_predictions(subnets=[])

    applied = weights.load_impact_strength()
    staged_r2 = trail_seen.get("r2")
    assert any(
        "r2" in rec.getMessage() and rec.levelno == logging.WARNING
        for rec in caplog.records
    ), "no warning names row 2 for the staged/applied mismatch"
    assert trail_seen.get("r2") is not None
    assert abs(trail_seen["r2"] - applied) < 1e-4, (
        f"trail carries {trail_seen['r2']}, soul map applied {applied}"
    )


def test_revoked_before_commit_refuses_save_and_runs_no_learning(ledger, sinks, monkeypatch):
    """A cycle revoked before its commit must refuse the save and run no learning."""
    before = ledger.read_bytes()
    state = {"rev": False}
    monkeypatch.setattr(resolver, "_cycle_writes_revoked_safe", lambda: state["rev"])

    def revoke_then_continue(*_a, **_kw):
        state["rev"] = True
        return None

    monkeypatch.setattr(resolver, "check_resolver_watchdog", revoke_then_continue)
    with pytest.raises(resolver.LedgerPersistSkipped):
        resolver._resolve_due_predictions(subnets=[])

    assert _sink_calls(sinks) == []
    assert ledger.read_bytes() == before


def test_revoked_between_save_and_flush_stops_remaining_learning(ledger, sinks, monkeypatch):
    """A revocation that lands after the save stops the learning that has not run yet.

    The save already happened, so the row stays resolved. Only the first effect runs.
    """
    state = {"rev": False}
    monkeypatch.setattr(resolver, "_cycle_writes_revoked_safe", lambda: state["rev"])

    def expert_then_revoke(*_a, **_kw):
        sinks.append("expert_nudge")
        state["rev"] = True

    monkeypatch.setattr(weights, "nudge_expert", expert_then_revoke)
    resolver._resolve_due_predictions(subnets=[])

    assert sinks == ["expert_nudge"], f"learning ran after revocation: {sinks}"
    rows = json.loads(ledger.read_text())
    assert [r["status"] for r in rows["resolved"] if r.get("id") == "r1"] == ["resolved"]
