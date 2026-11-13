"""Judge-weight writes must not pretend success when soul_map persist is refused."""

from __future__ import annotations

import json
import threading

import internal.store.soul_map_io as soul_map_io
from internal.judges import weights as judge_weights
from internal.judges.weights import load_judge_weights, nudge_judge


def test_nudge_judge_refused_write_returns_none(tmp_path, monkeypatch):
    path = tmp_path / "soul_map.json"
    path.write_text(
        json.dumps({"judge_weights": {"oracle": 0.35, "echo": 0.30, "pulse": 0.35}}),
        encoding="utf-8",
    )
    before = load_judge_weights(str(path))

    def _refuse(*_a, **_k):
        return soul_map_io.WriteResult(soul_map_io.WriteOutcome.REPLACE_FAILED, None)

    monkeypatch.setattr(soul_map_io, "write_soul_map", _refuse)
    after = nudge_judge("oracle", True, path=str(path))
    assert after is None
    assert load_judge_weights(str(path)) == before


def test_concurrent_nudges_preserve_both_judges(tmp_path, monkeypatch):
    path = tmp_path / "soul_map.json"
    path.write_text(json.dumps({"judge_weights": {"oracle": 0.35, "echo": 0.30, "pulse": 0.35}}))
    original = judge_weights.load_judge_weights
    barrier = threading.Barrier(2)
    errors = []

    def synchronized_read(*args, **kwargs):
        result = original(*args, **kwargs)
        try:
            barrier.wait(timeout=1)
        except threading.BrokenBarrierError:
            pass
        return result

    def nudge(name):
        try:
            judge_weights.nudge_judge(name, True, path=str(path))
        except Exception as exc:
            errors.append(exc)

    monkeypatch.setattr(judge_weights, "load_judge_weights", synchronized_read)
    monkeypatch.setattr("internal.learning.trail_bus.emit_weight_change", lambda *_a, **_kw: None)
    threads = [threading.Thread(target=nudge, args=(name,)) for name in ("oracle", "echo")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(5)
    assert errors == []
    final = json.loads(path.read_text())["judge_weights"]
    assert final["oracle"] == 0.37
    assert final["echo"] == 0.32
