"""Plan v3.1 regressions: B3 weights, B2 generation seed, B1 ledger paths."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from internal.council import resolver_scheduler, weights
from internal.calibration.pipeline import _save_calibration_state
from internal.council.formula_versions import record_calibration_version
from internal.learning import ledger_heal
from internal.store import soul_map_io
from internal.store.soul_map_io import BlobRead, WriteOutcome


def _declining_write_soul_map(real_write):
    """DECLINED only when mutator leaves canonical blob unchanged."""

    def wrapper(mutator, path=None):
        resolved = soul_map_io._resolve_path(path)
        checked = soul_map_io.read_blob_checked(resolved)
        if checked.kind == "loaded" and isinstance(checked.blob, dict):
            blob = copy.deepcopy(checked.blob)
        elif checked.kind == "missing":
            blob = {}
        else:
            return soul_map_io.WriteResult(WriteOutcome.READ_FAILED, None)
        prior = copy.deepcopy(blob)
        mutator(blob)
        if soul_map_io._canonical_blob_json(blob) == soul_map_io._canonical_blob_json(prior):
            return soul_map_io.WriteResult(WriteOutcome.DECLINED, prior)
        return real_write(mutator, path)

    return wrapper


# --- B3 ---


def test_save_raw_treats_declined_as_persist_ok(tmp_path, monkeypatch):
    soul = tmp_path / "soul_map.json"
    body = {"adversarial_state": {"council_weights": {"quant": 1.0}}}
    soul.write_text(json.dumps(body), encoding="utf-8")
    real = soul_map_io.write_soul_map
    monkeypatch.setattr(soul_map_io, "write_soul_map", _declining_write_soul_map(real))
    assert weights._save_raw(body, str(soul)) is True


def test_save_raw_still_refused_on_replace_failed(tmp_path, monkeypatch):
    soul = tmp_path / "soul_map.json"
    soul.write_text(json.dumps({}), encoding="utf-8")

    def refuse(*_a, **_k):
        return soul_map_io.WriteResult(WriteOutcome.REPLACE_FAILED, None)

    monkeypatch.setattr(soul_map_io, "write_soul_map", refuse)
    assert weights._save_raw({"x": 1}, str(soul)) is False


def test_save_impact_strength_raises_on_replace_failed(tmp_path, monkeypatch):
    soul = tmp_path / "soul_map.json"
    soul.write_text(json.dumps({}), encoding="utf-8")

    def refuse(*_a, **_k):
        return soul_map_io.WriteResult(WriteOutcome.REPLACE_FAILED, None)

    monkeypatch.setattr(soul_map_io, "write_soul_map", refuse)
    with pytest.raises(RuntimeError, match="impact strength persist refused"):
        weights.save_impact_strength(1.05, str(soul))


def test_rebalance_declined_no_trail_state_unchanged(tmp_path, monkeypatch):
    soul = tmp_path / "soul_map.json"
    preds = tmp_path / "predictions.json"
    flat = {"quant": 1.0, "hype": 1.0, "dark_horse": 1.0, "technical": 1.0}
    soul.write_text(
        json.dumps(
            {
                "adversarial_state": {"council_weights": dict(flat)},
                "expert_weights": dict(flat),
            }
        ),
        encoding="utf-8",
    )
    preds.write_text(
        json.dumps({"predictions": [], "resolved": [], "stats": {}}),
        encoding="utf-8",
    )
    real = soul_map_io.write_soul_map
    monkeypatch.setattr(soul_map_io, "write_soul_map", _declining_write_soul_map(real))
    emitted: list = []
    monkeypatch.setattr(
        "internal.learning.trail_bus.emit_weight_change",
        lambda *a, **k: emitted.append((a, k)),
    )
    before_bytes = soul.read_bytes()
    result = weights.rebalance_council_weights(
        predictions_path=str(preds),
        soul_map_path=str(soul),
        save=True,
    )
    assert result["ok"] is True
    assert result["trail_emitted"] is False
    assert emitted == []
    assert soul.read_bytes() == before_bytes


def test_save_signal_weights_raises_on_refused(tmp_path, monkeypatch):
    soul = tmp_path / "soul_map.json"
    soul.write_text(json.dumps({}), encoding="utf-8")

    def refuse(*_a, **_k):
        return soul_map_io.WriteResult(WriteOutcome.REPLACE_FAILED, None)

    monkeypatch.setattr(soul_map_io, "write_soul_map", refuse)
    with pytest.raises(RuntimeError, match="signal weight persist refused"):
        weights.save_signal_weights({"hour": {"rsi_crossover": 1.0}}, str(soul))


def test_nudge_signal_weight_declined_no_emit(tmp_path, monkeypatch):
    soul = tmp_path / "soul_map.json"
    soul.write_text(
        json.dumps(
            {
                "adversarial_state": {
                    "signal_weights": {"hour": {"rsi_crossover": 1.0}}
                }
            }
        ),
        encoding="utf-8",
    )
    real = soul_map_io.write_soul_map
    monkeypatch.setattr(soul_map_io, "write_soul_map", _declining_write_soul_map(real))
    emitted: list = []
    monkeypatch.setattr(
        "internal.learning.trail_bus.emit_weight_change",
        lambda *a, **k: emitted.append((a, k)),
    )
    # Wrong direction nudge clamped back to 1.0 → DECLINED, no trail
    out = weights.nudge_signal_weight("hour", "rsi_crossover", False, str(soul), scale=0.0)
    assert out == 1.0
    assert emitted == []


def test_save_calibration_state_declined_no_raise(tmp_path, monkeypatch):
    soul = tmp_path / "soul_map.json"
    event = {"kind": "noop", "v": 1}
    soul.write_text(
        json.dumps(
            {
                "adversarial_state": {
                    "calibration": {"last_event": event, "history": [event]}
                }
            }
        ),
        encoding="utf-8",
    )
    real = soul_map_io.write_soul_map
    monkeypatch.setattr(soul_map_io, "write_soul_map", _declining_write_soul_map(real))
    before_bytes = soul.read_bytes()
    # Empty patch → canonical blob unchanged → DECLINED (red on pre-honesty _save_raw).
    _save_calibration_state({}, soul_map_path=str(soul))
    assert soul.read_bytes() == before_bytes


def test_formula_version_persisted_flag_on_successful_save(tmp_path):
    soul = tmp_path / "soul_map.json"
    soul.write_text(
        json.dumps(
            {
                "adversarial_state": {
                    "council_weights": {"quant": 1.0, "hype": 1.0, "dark_horse": 1.0, "technical": 1.0},
                    "formula_versions": {
                        "council_weights": {"current": "1.0", "history": []},
                    },
                }
            }
        ),
        encoding="utf-8",
    )
    w = {"quant": 1.0, "hype": 1.0, "dark_horse": 1.0, "technical": 1.0}
    entry = record_calibration_version(
        cert={"passed": False, "proposed_accuracy": 0.5, "current_accuracy": 0.5},
        weights_before=w,
        weights_after=w,
        soul_map_path=str(soul),
        forced=False,
    )
    assert entry["version"] == "1.0"
    assert entry["version_bumped"] is False
    assert entry["bump_block_reason"] == "cert_not_passed"
    assert entry.get("persisted") is not False


def test_formula_version_persisted_false_when_write_refused(tmp_path, monkeypatch):
    soul = tmp_path / "soul_map.json"
    soul.write_text(
        json.dumps(
            {
                "adversarial_state": {
                    "council_weights": {"quant": 1.0, "hype": 1.0, "dark_horse": 1.0, "technical": 1.0},
                    "formula_versions": {
                        "council_weights": {"current": "1.0", "history": []},
                    },
                }
            }
        ),
        encoding="utf-8",
    )
    def refuse(*_a, **_k):
        return soul_map_io.WriteResult(WriteOutcome.REPLACE_FAILED, None)

    monkeypatch.setattr(soul_map_io, "write_soul_map", refuse)
    w = {"quant": 1.0, "hype": 1.0, "dark_horse": 1.0, "technical": 1.0}
    entry = record_calibration_version(
        cert={"passed": False, "proposed_accuracy": 0.5, "current_accuracy": 0.5},
        weights_before=w,
        weights_after=w,
        soul_map_path=str(soul),
        forced=False,
    )
    assert entry.get("persisted") is False


# --- B2 ---


def test_generation_seed_loaded_then_transient_single_read(tmp_path):
    good = {"prediction_resolver_scheduler": {"last_cycle": {"cycle_generation": 12}}}
    soul = tmp_path / "soul_map.json"
    soul.write_text(json.dumps(good), encoding="utf-8")
    calls = {"n": 0}

    def flaky(path):
        calls["n"] += 1
        if calls["n"] == 1:
            return BlobRead("loaded", copy.deepcopy(good))
        return BlobRead("transient", None, error="busy")

    sched = resolver_scheduler.PredictionResolverScheduler(
        soul_map_path=str(soul), refresh_minutes=15
    )
    with patch.object(soul_map_io, "read_blob_checked", flaky):
        sched._ensure_cycle_generation_seeded()
    assert sched._cycle_generation == 12
    assert sched._cycle_generation_seeded is True
    assert calls["n"] == 1


def test_generation_seed_malformed_scheduler_null_no_crash_no_latch(tmp_path):
    soul = tmp_path / "soul_map.json"
    soul.write_text(json.dumps({"prediction_resolver_scheduler": None}), encoding="utf-8")
    sched = resolver_scheduler.PredictionResolverScheduler(
        soul_map_path=str(soul), refresh_minutes=15
    )
    sched._ensure_cycle_generation_seeded()
    assert sched._cycle_generation_seeded is False


def test_generation_seed_invalid_cycle_generation_no_latch(tmp_path):
    soul = tmp_path / "soul_map.json"
    soul.write_text(
        json.dumps(
            {
                "prediction_resolver_scheduler": {
                    "last_cycle": {"cycle_generation": "not-int"}
                }
            }
        ),
        encoding="utf-8",
    )
    sched = resolver_scheduler.PredictionResolverScheduler(
        soul_map_path=str(soul), refresh_minutes=15
    )
    sched._ensure_cycle_generation_seeded()
    assert sched._cycle_generation_seeded is False


# --- B1 ---


def _decoy_day_predictions(netuid: int) -> dict:
    return {
        "predictions": [
            {"netuid": netuid, "horizon_type": "day", "status": "pending"},
        ],
        "resolved": [],
        "stats": {},
    }


def test_day_ledger_present_default_vs_explicit_predictions_path(tmp_path, monkeypatch):
    from internal.learning.loop_health import _day_ledger_present

    global_p = tmp_path / "global_predictions.json"
    alt_p = tmp_path / "alt_predictions.json"
    netuid = 42
    global_p.write_text(json.dumps(_decoy_day_predictions(netuid)), encoding="utf-8")
    alt_p.write_text(
        json.dumps({"predictions": [], "resolved": [], "stats": {}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "internal.learning.predictions_store.PREDICTIONS_PATH", str(global_p)
    )
    alt_data = json.loads(alt_p.read_text(encoding="utf-8"))
    assert _day_ledger_present(netuid) is True
    assert _day_ledger_present(netuid, alt_data) is False


def test_heal_record_failed_not_fooled_by_global_decoy(tmp_path, monkeypatch):
    from datetime import datetime, timezone

    global_p = tmp_path / "global_predictions.json"
    alt_p = tmp_path / "alt_predictions.json"
    daily = tmp_path / "daily_picks.json"
    netuid = 42
    price = 1.23
    today = datetime.now(timezone.utc).date().isoformat()

    global_p.write_text(json.dumps(_decoy_day_predictions(netuid)), encoding="utf-8")
    alt_p.write_text(
        json.dumps({"predictions": [], "resolved": [], "stats": {}}),
        encoding="utf-8",
    )
    daily.write_text(
        json.dumps(
            [
                {
                    "date": today,
                    "action": "long",
                    "has_pick": True,
                    "pick_netuid": netuid,
                    "pick": {
                        "action": "long",
                        "subnet": {"netuid": netuid, "name": f"SN{netuid}", "price": price},
                        "prediction": {
                            "reference_price": price,
                            "predicted_pct": 2.0,
                            "horizon_hours": 24,
                        },
                    },
                    "market_context": {},
                }
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "internal.learning.predictions_store.PREDICTIONS_PATH", str(global_p)
    )
    monkeypatch.setattr("internal.learning.ledger_heal.DAILY_PICKS_PATH", str(daily))
    monkeypatch.setattr(
        "internal.learning.prediction_loop.record_pick",
        lambda *a, **k: SimpleNamespace(
            kind="skipped", reason="duplicate", prediction=None
        ),
    )

    summary = ledger_heal.heal_daily_pick_ledger(
        dry_run=False,
        daily_picks_path=str(daily),
        predictions_path=str(alt_p),
    )
    assert summary["ok"] is False
    assert summary["healed"] is False
    assert summary["reason"] == "record_failed"
    assert summary["netuid"] == netuid
    alt_after = json.loads(alt_p.read_text(encoding="utf-8"))
    assert not any(
        r.get("horizon_type") == "day" and int(r.get("netuid", -1)) == netuid
        for r in alt_after.get("predictions") or []
    )
