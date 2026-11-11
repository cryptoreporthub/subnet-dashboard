"""Judge-weight writes must not pretend success when soul_map persist is refused."""

from __future__ import annotations

import json

import internal.store.soul_map_io as soul_map_io
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
