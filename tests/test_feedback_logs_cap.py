"""FEEDBACK_LOGS_MAX cap on MindmapBridge (memory-only heal)."""

from __future__ import annotations

import json
from pathlib import Path

from internal.council.mindmap_bridge import FEEDBACK_LOGS_MAX, MindmapBridge


def test_cap_holds_across_load_and_save(tmp_path):
    path = tmp_path / "soul_map.json"
    path.write_text(
        json.dumps({"soul_map_state": {}, "feedback_logs": [{"i": i} for i in range(5)]}),
        encoding="utf-8",
    )
    bridge = MindmapBridge(persistence_path=str(path))
    for i in range(20):
        bridge.log_feedback(
            {"decisions": []},
            {"recommendations": {}},
        )
    assert len(bridge.feedback_logs) <= FEEDBACK_LOGS_MAX
    # Reload
    bridge2 = MindmapBridge(persistence_path=str(path))
    assert len(bridge2.feedback_logs) <= FEEDBACK_LOGS_MAX
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(on_disk["feedback_logs"], list)
    assert len(on_disk["feedback_logs"]) <= FEEDBACK_LOGS_MAX


def test_oversize_legacy_array_trims_on_load(tmp_path):
    path = tmp_path / "soul_map.json"
    path.write_text(
        json.dumps(
            {
                "soul_map_state": {"keep": True},
                "feedback_logs": [{"i": i} for i in range(50)],
                "adversarial_state": {"x": 1},
            }
        ),
        encoding="utf-8",
    )
    bridge = MindmapBridge(persistence_path=str(path))
    assert len(bridge.feedback_logs) == FEEDBACK_LOGS_MAX
    assert bridge.feedback_logs[0]["i"] == 40  # last 10
    # Memory-only: disk not rewritten until a save path runs
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert len(on_disk["feedback_logs"]) == 50


def test_non_list_payload_safe(tmp_path):
    path = tmp_path / "soul_map.json"
    path.write_text(
        json.dumps({"soul_map_state": {}, "feedback_logs": {"oops": True}}),
        encoding="utf-8",
    )
    bridge = MindmapBridge(persistence_path=str(path))
    assert bridge.feedback_logs == []
