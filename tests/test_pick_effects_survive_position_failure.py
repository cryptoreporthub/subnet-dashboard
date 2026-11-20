"""A committed pick keeps its mindmap trail and soul-map mirror when opening judge positions fails.

The pick row is saved to the predictions ledger before judge positions open. If opening them
raises, the pick is still committed, so its trail and mirror must still be written.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from internal.council import mindmap_bridge, weights
from internal.judges import portfolios
from internal.learning import prediction_loop

CANON = {"quant": 1.0, "hype": 1.0, "dark_horse": 1.0, "technical": 1.0}


class _TrailSpy:
    calls: list = []

    def __init__(self, *_a, **_kw):
        pass

    def append_learning_trail(self, entry, **_kw):
        _TrailSpy.calls.append(entry)
        return SimpleNamespace()


@pytest.fixture
def world(tmp_path, monkeypatch):
    ledger = tmp_path / "predictions.json"
    soul = tmp_path / "soul_map.json"
    monkeypatch.setattr(portfolios, "PORTFOLIOS_PATH", str(tmp_path / "portfolios.json"))
    monkeypatch.setattr(prediction_loop, "_link_scenario_memory", lambda *_a, **_kw: None)
    monkeypatch.setattr(prediction_loop, "load_weights", lambda *_a, **_kw: dict(CANON))
    monkeypatch.setattr(weights, "_load_raw", lambda *_a, **_kw: _read_soul(soul))
    monkeypatch.setattr(weights, "_save_raw", lambda data, *_a, **_kw: _write_soul(soul, data))
    monkeypatch.setattr(mindmap_bridge, "MindmapBridge", _TrailSpy)
    _TrailSpy.calls = []
    return SimpleNamespace(ledger=ledger, soul=soul)


def _read_soul(path):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _pick_trail_ids():
    """Prediction ids of pick trail entries. Trail-bus events share the spy but carry no prediction_id."""
    return [c["prediction_id"] for c in _TrailSpy.calls if c.get("prediction_id")]


def _write_soul(path, data):
    path.write_text(json.dumps(data), encoding="utf-8")
    return True


PICK = {
    "subnet": {"netuid": 7, "name": "Seven"},
    "confidence": 0.7,
    "expert_contributions": {"quant": 0.6},
    "action": "long",
}
SUBNET = {"netuid": 7, "name": "Seven", "price": 12.0, "price_change_24h": 2.0}


def _record(world):
    return prediction_loop.record_pick(
        dict(PICK), dict(SUBNET), horizon_type="hour", predictions_path=str(world.ledger)
    )


def _fail_positions(monkeypatch):
    def _positions_fail(*_a, **_kw):
        raise RuntimeError("portfolio write failed after the ledger save")

    monkeypatch.setattr(portfolios, "open_positions_for_prediction", _positions_fail)


def test_control_trail_and_mirror_written_when_positions_open(world, monkeypatch):
    """Control: with positions opening normally, the spy and the mirror see the pick."""
    monkeypatch.setattr(portfolios, "open_positions_for_prediction", lambda *_a, **_kw: None)

    result = _record(world)

    prediction_id = result.prediction["id"]
    assert _pick_trail_ids() == [prediction_id]
    mirrored = _read_soul(world.soul)["soul_map_state"]["last_hour_pick"]
    assert mirrored["prediction_id"] == prediction_id


def _bus_entries():
    """Trail-bus events: the spy entries that carry no prediction_id."""
    return [c for c in _TrailSpy.calls if not c.get("prediction_id")]


def test_control_trail_bus_events_written(world, monkeypatch):
    monkeypatch.setattr(portfolios, "open_positions_for_prediction", lambda *_a, **_kw: None)

    _record(world)

    assert len(_bus_entries()) == 2, "conviction_update and signal_triggered should both reach the trail"


def test_trail_bus_events_written_when_position_open_raises(world, monkeypatch):
    _fail_positions(monkeypatch)

    _record(world)

    assert len(_bus_entries()) == 2, "trail-bus events were not written after the position failure"


def test_trail_written_when_position_open_raises(world, monkeypatch):
    _fail_positions(monkeypatch)

    result = _record(world)

    assert result.kind is prediction_loop.PickRecordKind.INDETERMINATE
    assert result.reason == "positions_incomplete"
    prediction_id = result.prediction["id"]
    saved_ids = [row["id"] for row in json.loads(world.ledger.read_text())["predictions"]]
    assert prediction_id in saved_ids, "the pick should be committed to the ledger before positions open"
    assert _pick_trail_ids() == [prediction_id], "the committed pick's mindmap trail was not written"


def test_mirror_written_when_position_open_raises(world, monkeypatch):
    _fail_positions(monkeypatch)

    result = _record(world)

    prediction_id = result.prediction["id"]
    mirrored = _read_soul(world.soul).get("soul_map_state", {}).get("last_hour_pick") or {}
    assert mirrored.get("prediction_id") == prediction_id, "the committed pick's soul-map mirror was not written"


def test_retry_after_position_failure_writes_trail_once(world, monkeypatch):
    _fail_positions(monkeypatch)

    first = _record(world)
    second = _record(world)

    assert second.kind is prediction_loop.PickRecordKind.SKIPPED
    assert second.reason == "duplicate"
    assert _pick_trail_ids() == [first.prediction["id"]]
