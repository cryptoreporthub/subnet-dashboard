"""Pending mindmap trail rows drop on declined soul_map writes."""

from __future__ import annotations

import json

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
