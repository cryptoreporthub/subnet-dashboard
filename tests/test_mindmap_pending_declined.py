"""Pending mindmap trail rows drop on declined soul_map writes."""

from __future__ import annotations

import json
import hashlib
from types import SimpleNamespace
from unittest.mock import patch

from internal.council.mindmap_bridge import (
    MindmapBridge,
    _pending_key,
    _snapshot_pending,
    pending_resolved_ids,
)
from internal.store import soul_map_io as smio


def test_declined_write_drops_pending_rows(tmp_path, monkeypatch):
    soul = tmp_path / "soul_map.json"
    soul.write_text(
        json.dumps({"soul_map_state": {"learning_trail": []}}),
        encoding="utf-8",
    )
    key = _pending_key(str(soul))

    def _decline(mutator, path=None, **_kwargs):
        blob = json.loads(soul.read_text(encoding="utf-8"))
        mutator(blob)
        return smio.WriteResult(smio.WriteOutcome.DECLINED, blob)

    monkeypatch.setattr(
        "internal.council.mindmap_bridge.write_soul_map", _decline
    )
    bridge = MindmapBridge(persistence_path=str(soul))
    bridge.append_learning_trail({"event_type": "pick", "time": "T1"})
    _through, rows, _resolved = _snapshot_pending(key)
    assert rows == []


def test_failed_write_keeps_pending_rows(tmp_path, monkeypatch):
    soul = tmp_path / "soul_map.json"
    soul.write_text(
        json.dumps({"soul_map_state": {"learning_trail": []}}),
        encoding="utf-8",
    )

    def _refuse(*_a, **_k):
        return smio.WriteResult(smio.WriteOutcome.REPLACE_FAILED, None)

    monkeypatch.setattr(
        "internal.council.mindmap_bridge.write_soul_map", _refuse
    )
    bridge = MindmapBridge(persistence_path=str(soul))
    bridge.append_learning_trail(
        {"event_type": "pick", "time": "T-fail"},
        resolved_prediction_id="pid-1",
    )
    assert pending_resolved_ids(str(soul)) == ["pid-1"]


def test_distinct_same_second_events_both_persist(tmp_path):
    soul = tmp_path / "soul_map.json"
    soul.write_text(json.dumps({"soul_map_state": {"learning_trail": []}}))
    bridge = MindmapBridge(persistence_path=str(soul))
    bridge.append_learning_trail({"event_type": "weight_change", "time": "same", "event_id": "first"})
    bridge.append_learning_trail({"event_type": "weight_change", "time": "same", "event_id": "second"})
    trail = json.loads(soul.read_text())["soul_map_state"]["learning_trail"]
    assert [entry["event_id"] for entry in trail] == ["first", "second"]


def test_applied_without_target_on_disk_is_not_committed(tmp_path, monkeypatch):
    soul = tmp_path / "soul_map.json"
    soul.write_text(json.dumps({"soul_map_state": {"learning_trail": []}}))
    monkeypatch.setattr(
        "internal.council.mindmap_bridge.write_soul_map",
        lambda *_a, **_kw: smio.WriteResult(smio.WriteOutcome.APPLIED, {"soul_map_state": {}}),
    )
    outcome = MindmapBridge(persistence_path=str(soul)).append_learning_trail(
        {"event_type": "weight_change", "time": "same", "event_id": "absent"}
    )
    assert getattr(outcome, "kind", None) in ("evicted", "failed", "buffered")
    assert json.loads(soul.read_text())["soul_map_state"]["learning_trail"] == []


def test_buffered_trail_is_not_reported_committed(tmp_path, monkeypatch):
    soul = tmp_path / "soul_map.json"
    soul.write_text(json.dumps({"soul_map_state": {"learning_trail": []}}))
    monkeypatch.setattr(
        "internal.council.mindmap_bridge.write_soul_map",
        lambda *_a, **_kw: smio.WriteResult(smio.WriteOutcome.REPLACE_FAILED, None),
    )
    outcome = MindmapBridge(persistence_path=str(soul)).append_learning_trail(
        {"event_type": "weight_change", "time": "same", "event_id": "buffered"}
    )
    assert getattr(outcome, "kind", None) == "buffered"
    assert json.loads(soul.read_text())["soul_map_state"]["learning_trail"] == []


def test_replayed_learning_event_has_deterministic_id(tmp_path, monkeypatch):
    from internal.council import weights
    from internal.learning.trail_events import emit_prediction_resolved

    soul = tmp_path / "soul_map.json"
    soul.write_text(json.dumps({"soul_map_state": {"learning_trail": []}}))
    monkeypatch.setattr(weights, "SOUL_MAP_PATH", str(soul))
    prediction = {"id": "p1", "correct": True, "learning": {"key": "learning-1"}}
    emit_prediction_resolved(prediction, "quant")
    emit_prediction_resolved(prediction, "quant")
    trail = json.loads(soul.read_text())["soul_map_state"]["learning_trail"]
    assert len(trail) == 1
    assert trail[0]["event_id"] == hashlib.sha256(b"learning-1|prediction_resolved|0").hexdigest()[:16]


def test_legacy_same_event_is_not_replayed_twice(tmp_path):
    from internal.council.mindmap_bridge import _replay_trail_rows

    entry = {"event_type": "legacy", "time": "same"}
    state = {"learning_trail": [dict(entry)]}
    _replay_trail_rows(state, [(entry, None)])
    assert state["learning_trail"] == [entry]


def test_rebalance_counts_only_committed_trail_events(tmp_path):
    from internal.council.weights import rebalance_council_weights

    soul = tmp_path / "soul_map.json"
    preds = tmp_path / "predictions.json"
    soul.write_text("{}")
    preds.write_text('{"resolved":[]}')
    before = {"quant": 2.0, "hype": 2.0, "dark_horse": 1.0, "technical": 1.0}
    after = {"quant": 1.0, "hype": 1.0, "dark_horse": 1.0, "technical": 1.0}
    with patch("internal.council.weights.save_weights", return_value=(True, True)), \
         patch("internal.council.weights.load_weights", return_value=before), \
         patch("internal.council.weights.soft_blend_weights", return_value=after), \
         patch("internal.council.weights.replay_weights_from_predictions", return_value=after), \
         patch("internal.council.weights.merged_replay_rows", return_value=([], {})), \
         patch("internal.learning.trail_bus.emit_weight_change", side_effect=[
             SimpleNamespace(kind="committed"), SimpleNamespace(kind="buffered"),
         ]):
        result = rebalance_council_weights(predictions_path=str(preds), soul_map_path=str(soul), save=True)
    assert result["trail_emitted"] is True
    assert result["ok"] is False
    assert result["trail_emit_planned"] == 2
    assert result["trail_emit_committed"] == 1


def test_target_evicted_from_trail_is_not_committed(tmp_path, monkeypatch):
    soul = tmp_path / "soul_map.json"
    soul.write_text(json.dumps({"soul_map_state": {"learning_trail": []}}))

    def write_and_evict(mutator, *_a, **_kw):
        blob = {"soul_map_state": {"learning_trail": []}}
        mutator(blob)
        blob["soul_map_state"]["learning_trail"] = [
            {"event_type": "other", "time": str(i), "event_id": str(i)} for i in range(200)
        ]
        soul.write_text(json.dumps(blob))
        return smio.WriteResult(smio.WriteOutcome.APPLIED, blob)

    monkeypatch.setattr("internal.council.mindmap_bridge.write_soul_map", write_and_evict)
    result = MindmapBridge(persistence_path=str(soul)).append_learning_trail(
        {"event_type": "weight_change", "time": "same", "event_id": "evicted"}
    )
    assert getattr(result, "kind", None) == "evicted"
