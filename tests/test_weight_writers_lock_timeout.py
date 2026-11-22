"""A held soul-map lock must make weight writers refuse, not raise (Gemini #1598)."""

import fcntl
import json

import pytest

from internal.council import weights as council_weights
from internal.judges import weights as judge_weights
from internal.store import soul_map_io


@pytest.fixture
def held_soul_map(tmp_path, monkeypatch):
    path = tmp_path / "soul_map.json"
    original = {"judge_weights": {"oracle": 0.5}}
    path.write_text(json.dumps(original), encoding="utf-8")
    monkeypatch.setattr(soul_map_io, "_SOUL_MAP_LOCK_DEADLINE_SECONDS", 0.1)

    holder = open(str(path) + ".lock", "a+", encoding="utf-8")
    fcntl.flock(holder.fileno(), fcntl.LOCK_EX)
    try:
        yield path, original
    finally:
        fcntl.flock(holder.fileno(), fcntl.LOCK_UN)
        holder.close()


def _writers(path):
    p = str(path)
    return {
        "save_weights": lambda: council_weights.save_weights({"oracle": 0.4}, path=p),
        "nudge_expert": lambda: council_weights.nudge_expert("oracle", True, path=p),
        "nudge_signal_weight": lambda: council_weights.nudge_signal_weight(
            "hour", "rsi", True, path=p
        ),
        "nudge_impact_strength": lambda: council_weights.nudge_impact_strength(
            True, tier=None, path=p
        ),
        "save_judge_weights": lambda: judge_weights.save_judge_weights(
            {"oracle": 0.4}, path=p
        ),
        "nudge_judge": lambda: judge_weights.nudge_judge("oracle", True, path=p),
    }


@pytest.mark.parametrize(
    "name",
    [
        "save_weights",
        "nudge_expert",
        "nudge_signal_weight",
        "nudge_impact_strength",
        "save_judge_weights",
        "nudge_judge",
    ],
)
def test_writer_refuses_under_held_lock_without_raising(held_soul_map, name):
    path, original = held_soul_map

    _writers(path)[name]()  # must not raise SoulMapLockWaitTimeout

    assert json.loads(path.read_text(encoding="utf-8")) == original
