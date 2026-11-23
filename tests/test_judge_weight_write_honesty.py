"""Judge-weight writes must not pretend success when soul_map persist is refused."""

from __future__ import annotations

import json
import threading

from internal.judges import weights as judge_weights
from internal.judges.weights import load_judge_weights, nudge_judge


def test_nudge_judge_refused_write_returns_none(tmp_path, monkeypatch):
    path = tmp_path / "soul_map.json"
    path.write_text(
        json.dumps({"judge_weights": {"oracle": 0.35, "echo": 0.30, "pulse": 0.35}}),
        encoding="utf-8",
    )
    before = load_judge_weights(str(path))

    from internal.store import ledger_db

    def _refuse(*_a, **_k):
        raise ledger_db.LedgerUnreadable("write refused")

    monkeypatch.setattr(ledger_db, "transaction", _refuse)
    after = nudge_judge("oracle", True, path=str(path))
    assert after is None
    assert load_judge_weights(str(path)) == before


def test_concurrent_nudges_preserve_both_judges(tmp_path, monkeypatch):
    path = tmp_path / "soul_map.json"
    path.write_text(json.dumps({"judge_weights": {"oracle": 0.35, "echo": 0.30, "pulse": 0.35}}))
    # Both nudges start together, so a weight read taken before the soul-map lock overlaps.
    barrier = threading.Barrier(2)
    reached: list[str] = []
    errors = []

    def nudge(name):
        try:
            barrier.wait(timeout=5)
            reached.append(name)
            judge_weights.nudge_judge(name, True, path=str(path))
        except Exception as exc:
            errors.append(exc)

    monkeypatch.setattr("internal.learning.trail_bus.emit_weight_change", lambda *_a, **_kw: None)
    threads = [threading.Thread(target=nudge, args=(name,)) for name in ("oracle", "echo")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(5)
    assert errors == [], errors
    assert sorted(reached) == ["echo", "oracle"], "a nudge never reached nudge_judge"
    final = load_judge_weights(str(path))
    assert final["oracle"] == 0.37
    assert final["echo"] == 0.32
