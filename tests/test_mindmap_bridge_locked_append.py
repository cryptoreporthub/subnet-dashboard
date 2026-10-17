"""Appending trail/feedback rows must not drop concurrent writers' soul-map updates."""

from internal.council.mindmap_bridge import MindmapBridge
from internal.store.soul_map_io import read_soul_map, write_soul_map


def test_trail_append_preserves_concurrent_soul_map_state(tmp_path):
    path = str(tmp_path / "soul_map.json")
    bridge = MindmapBridge(persistence_path=path)  # loaded before the other writer runs

    write_soul_map(
        lambda blob: blob.setdefault("soul_map_state", {}).__setitem__("pump_ladder", {"x": 1}),
        path,
    )
    write_soul_map(lambda blob: blob.__setitem__("expert_weights", {"hype": 1.5}), path)

    bridge.append_learning_trail({"signal": "user_feedback", "evidence": {"note": "n"}})

    blob = read_soul_map(path)
    assert blob["soul_map_state"]["pump_ladder"] == {"x": 1}
    assert blob["expert_weights"] == {"hype": 1.5}
    assert blob["soul_map_state"]["learning_trail"][-1]["signal"] == "user_feedback"


def test_feedback_log_append_preserves_concurrent_state_and_caps(tmp_path):
    path = str(tmp_path / "soul_map.json")
    bridge = MindmapBridge(persistence_path=path)
    write_soul_map(lambda blob: blob.__setitem__("judge_weights", {"oracle": 0.3}), path)

    for _ in range(15):
        bridge.log_feedback({"decisions": []}, {"recommendations": {}})

    blob = read_soul_map(path)
    assert blob["judge_weights"] == {"oracle": 0.3}
    assert len(blob["feedback_logs"]) == 10
