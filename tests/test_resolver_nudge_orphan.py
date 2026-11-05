"""An abandoned resolver cycle must not nudge learning state.

resolver._save_json skips the predictions write once a cycle is revoked, but the
impact, expert, and signal nudges write their own files. An orphan cycle that
keeps grading therefore lands nudges that the revived cycle applies again to
the same still-pending prediction.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

import pytest

import internal.council.resolver as resolver
import internal.council.resolver_scheduler as resolver_scheduler
import internal.council.weights as weights


NETUID = 7


@pytest.fixture
def harness(tmp_path, monkeypatch):
    predictions_path = tmp_path / "predictions.json"
    price_cache_path = tmp_path / "price_cache.json"
    monkeypatch.setattr(resolver, "PREDICTIONS_PATH", str(predictions_path))
    monkeypatch.setattr(resolver, "PRICE_CACHE_PATH", str(price_cache_path))
    monkeypatch.setattr(resolver, "_skip_council_learning", lambda *_a, **_k: False)
    assert resolver._in_replay_mode() is False

    resolve_at = datetime.now(timezone.utc) - timedelta(minutes=5)
    stamp = resolve_at.isoformat().replace("+00:00", "Z")
    rows = [
        {
            "id": pred_id,
            "netuid": NETUID,
            "name": "Nudge Orphan Test",
            "direction": "up",
            # dedupe keys on (netuid, predicted_pct, 5min bucket): distinct pct keeps both rows pending.
            "predicted_pct": pct,
            "reference_price": 100.0,
            "resolve_at": stamp,
            "created_at": (resolve_at - timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
            "status": "pending",
            "horizon_type": "hour",
            "horizon_hours": 1.0,
        }
        for pred_id, pct in (("in-flight-row", 2.0), ("orphan-row", 3.0))
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
    monkeypatch.setattr(resolver, "_nudge_weights", lambda *_a, **_k: None)
    monkeypatch.setattr(resolver, "_nudge_weights_from_judge_audit", lambda *_a, **_k: None)
    monkeypatch.setattr(resolver, "_record_scenario_outcome", lambda *_a, **_k: None)
    monkeypatch.setattr(resolver, "_nudge_signal_weights", lambda *_a, **_k: None)
    return predictions_path


def _run_cycle(
    monkeypatch,
    sched,
    gen: int,
    nudges: List[Dict[str, Any]],
    abandon_on_first_nudge: bool,
) -> None:
    """Run one resolver pass as cycle `gen`, recording each impact nudge and whether it was revoked."""
    sched._persist_owner_gen = gen
    timing = resolver_scheduler._CycleTiming()
    timing.set_owner_gen(gen, sched)
    token = resolver_scheduler._cycle_timing.set(timing)
    state = {"abandoned": False}

    def spy_nudge(correct, tier=None, **_kwargs):
        nudges.append({"gen": gen, "revoked": resolver_scheduler.cycle_writes_revoked()})
        if abandon_on_first_nudge and not state["abandoned"]:
            state["abandoned"] = True
            sched._abandon_inflight_cycle()
        return 0.5

    monkeypatch.setattr(resolver, "nudge_impact_strength", spy_nudge)
    try:
        resolver._resolve_due_predictions(subnets=[{"netuid": NETUID, "price": 110.0}])
    finally:
        resolver_scheduler._cycle_timing.reset(token)


def test_abandoned_cycle_lands_no_impact_nudge(harness, monkeypatch):
    sched = resolver_scheduler.PredictionResolverScheduler()
    nudges: List[Dict[str, Any]] = []

    _run_cycle(monkeypatch, sched, 1, nudges, abandon_on_first_nudge=True)
    _run_cycle(monkeypatch, sched, 2, nudges, abandon_on_first_nudge=False)

    orphan = [n for n in nudges if n["revoked"]]
    print(f"\n[NUDGE_COUNT] total={len(nudges)} orphan={len(orphan)} calls={nudges}")
    assert orphan == []


@pytest.mark.parametrize("revoke_at", ["expert", "impact", "scenario", "signal"])
def test_revoked_cycle_applies_no_later_learning_write(harness, monkeypatch, revoke_at):
    """Revocation landing mid-row must stop every later learning write for that cycle."""
    # The harness rows carry no council evidence, so the expert nudge is gated off.
    # Open that gate here so the expert write point is reachable.
    import internal.council.expert_attribution as expert_attribution
    import internal.council.signal_expert as signal_expert
    import internal.learning.evidence as evidence

    monkeypatch.setattr(
        expert_attribution, "resolve_expert_attribution", lambda *_a, **_k: ("alpha", "existing")
    )
    monkeypatch.setattr(signal_expert, "expert_for_replay_row", lambda *_a, **_k: "alpha")
    monkeypatch.setattr(evidence, "evidence_population", lambda *_a, **_k: "council_published")
    sched = resolver_scheduler.PredictionResolverScheduler()
    sched._persist_owner_gen = 1
    timing = resolver_scheduler._CycleTiming()
    timing.set_owner_gen(1, sched)
    token = resolver_scheduler._cycle_timing.set(timing)
    writes: List[Dict[str, Any]] = []
    revoke_point_ran = {"ran": False}

    def recorder(name):
        def spy(*_args, **_kwargs):
            writes.append({"name": name, "revoked": resolver_scheduler.cycle_writes_revoked()})
            if name == revoke_at:
                revoke_point_ran["ran"] = True
                sched._abandon_inflight_cycle()
            return 0.5

        return spy

    monkeypatch.setattr(resolver, "_nudge_weights", recorder("expert"))
    monkeypatch.setattr(resolver, "nudge_impact_strength", recorder("impact"))
    monkeypatch.setattr(resolver, "_record_scenario_outcome", recorder("scenario"))
    monkeypatch.setattr(resolver, "_nudge_signal_weights", recorder("signal"))
    monkeypatch.setattr(resolver, "atomic_finalize_resolution", recorder("finalize"))
    try:
        resolver._resolve_due_predictions(subnets=[{"netuid": NETUID, "price": 110.0}])
    finally:
        resolver_scheduler._cycle_timing.reset(token)

    assert revoke_point_ran["ran"], f"{revoke_at} write never ran, so the test proves nothing"
    after_revoke = [w["name"] for w in writes if w["revoked"]]
    print(f"\n[WRITES] revoke_at={revoke_at} calls={writes}")
    assert after_revoke == []


def test_abandon_cannot_revoke_between_impact_check_and_write(harness, monkeypatch):
    """The impact check and its write sit under the release guard, so an abandon waits for both."""
    import threading

    sched = resolver_scheduler.PredictionResolverScheduler()
    sched._persist_owner_gen = 1
    timing = resolver_scheduler._CycleTiming()
    timing.set_owner_gen(1, sched)
    token = resolver_scheduler._cycle_timing.set(timing)
    abandon_thread = None
    seen: Dict[str, Any] = {}

    def impact_while_abandon_races(correct, tier=None, **_kwargs):
        nonlocal abandon_thread
        if "abandon_blocked" not in seen:
            abandon_thread = threading.Thread(target=sched._abandon_inflight_cycle)
            abandon_thread.start()
            abandon_thread.join(0.2)
            seen["abandon_blocked"] = abandon_thread.is_alive()
            seen["owner_gen"] = sched._persist_owner_gen
        return 0.5

    monkeypatch.setattr(resolver, "nudge_impact_strength", impact_while_abandon_races)
    try:
        resolver._resolve_due_predictions(subnets=[{"netuid": NETUID, "price": 110.0}])
    finally:
        resolver_scheduler._cycle_timing.reset(token)
    abandon_thread.join(5)

    assert seen == {"abandon_blocked": True, "owner_gen": 1}
    assert sched._persist_owner_gen is None
