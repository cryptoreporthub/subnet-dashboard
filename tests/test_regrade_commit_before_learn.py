"""Regrade learns only after its ledger save succeeds.

regrade_expired_predictions grades expired rows that now have candles, then saves
them with trigger="regrade". Before the fix, its learning ran before that save, so a
refused save left the learning applied to a row still marked expired. The next cycle
then applied it again. These tests observe the write sinks on disk, not the helpers.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone

import pytest

from internal.council import pick_history, prediction_trace, resolver, scenario_memory, weights
from internal.council import signal_expert
from internal.learning import evidence, trail_bus, trail_events

NETUID = 7
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


def _expired_row(resolve_at: str) -> dict:
    return {
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


@pytest.fixture
def regrade_setup(tmp_path, monkeypatch):
    now = datetime.now(timezone.utc)
    resolve_at_dt = now - timedelta(hours=3)
    resolve_at = resolve_at_dt.isoformat().replace("+00:00", "Z")
    preds = tmp_path / "predictions.json"
    preds.write_text(json.dumps({"predictions": [], "resolved": [_expired_row(resolve_at)], "stats": {}}))
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
    monkeypatch.setattr(resolver, "PREDICTIONS_PATH", str(preds))
    monkeypatch.setattr(resolver, "PRICE_CACHE_PATH", str(cache))
    monkeypatch.setattr(weights, "SOUL_MAP_PATH", str(tmp_path / "soul_map.json"))
    monkeypatch.setattr(resolver, "hydrate_candles_for_netuid", lambda *_a, **_kw: False)
    monkeypatch.setattr(resolver, "_skip_council_learning", lambda _p: False)
    monkeypatch.setattr(resolver, "_cycle_writes_revoked_safe", lambda: False)
    monkeypatch.setattr(evidence, "evidence_population", lambda _row: "council_published")
    monkeypatch.setattr(signal_expert, "expert_for_replay_row", lambda _row: "oracle")
    return preds


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


def test_refused_regrade_save_runs_no_learning(regrade_setup, sinks, monkeypatch):
    before = regrade_setup.read_bytes()
    real_replace = os.replace

    def refuse(src, dst):
        if str(dst) == str(regrade_setup):
            raise OSError("injected ledger failure")
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", refuse)
    try:
        resolver.regrade_expired_predictions(live_prices={})
    except Exception:
        pass

    assert [n for n in sinks if n in SINKS] == [], f"regrade learned before its save: {sinks}"
    assert regrade_setup.read_bytes() == before


def test_successful_regrade_runs_each_sink_once(regrade_setup, sinks):
    resolver.regrade_expired_predictions(live_prices={})

    counts = {name: sinks.count(name) for name in SINKS}
    assert counts == {name: 1 for name in SINKS}, counts



def test_conflicted_regrade_row_is_not_reported_as_regraded(regrade_setup, sinks, monkeypatch):
    """When one regrade conflicts and another commits, only the committed row counts as regraded."""
    disk = json.loads(regrade_setup.read_text())
    second = dict(disk["resolved"][0], id="regrade-2")
    disk["resolved"].append(second)
    regrade_setup.write_text(json.dumps(disk))
    real_commit = resolver._commit_ledger_changes

    def other_writer_then_commit(before, after, **kwargs):
        cur = json.loads(regrade_setup.read_text())
        for row in cur["resolved"]:
            if row.get("id") == "regrade-1":
                row["note"] = "other writer"
        regrade_setup.write_text(json.dumps(cur))
        return real_commit(before, after, **kwargs)

    monkeypatch.setattr(resolver, "_commit_ledger_changes", other_writer_then_commit)
    out = resolver.regrade_expired_predictions(live_prices={})

    assert out["regraded"] == 1, f"conflicted regrade counted as regraded: {out}"
