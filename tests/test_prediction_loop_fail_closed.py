"""Prediction-loop writers fail closed on unreadable judge books and keep sibling soul-map keys (Gemini #1603)."""

import json
import os

import pytest

from internal.council import weights as council_weights
from internal.judges import portfolios as jp
from internal.judges import postmortems
from internal.learning import prediction_loop as pl


def _primed_soul_map(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    os.makedirs("data", exist_ok=True)
    path = os.path.join("data", "soul_map.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"judge_weights": {"oracle": 0.5}}, fh)
    council_weights._load_raw(path)
    with open(path, encoding="utf-8") as fh:
        on_disk = json.load(fh)
    on_disk["sibling_writer_key"] = {"kept": True}
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(on_disk, fh)
    return path


def _sibling_survives(path) -> bool:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh).get("sibling_writer_key") == {"kept": True}


def test_reconcile_fails_closed_on_corrupt_judge_book(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    os.makedirs("data", exist_ok=True)
    book = os.path.join("data", "judge_portfolios.json")
    with open(book, "w", encoding="utf-8") as fh:
        fh.write("{corrupt")
    monkeypatch.setattr(jp, "PORTFOLIOS_PATH", book)
    preds = tmp_path / "predictions.json"
    preds.write_text(json.dumps({"predictions": [], "resolved": []}), encoding="utf-8")

    with pytest.raises(jp.PortfolioUnreadable):
        pl.reconcile_judge_positions(predictions_path=str(preds))


def _wrong_resolved_row():
    return {
        "id": "p1",
        "status": "resolved",
        "outcome": "miss",
        "correct": False,
        "actual_pct": -2.0,
        "netuid": 1,
        "name": "A",
        "direction": "up",
        "created_at": "2026-07-01T10:00:00Z",
    }


def test_postmortem_read_error_skips_judge_instead_of_rewriting(monkeypatch):
    observation = {"kind": "readable", "data": {"oracle": {"closed_positions": [{"id": "p1"}]}}, "error": None}
    data = {"predictions": [], "resolved": [_wrong_resolved_row()]}
    written = []
    monkeypatch.setattr(postmortems, "record", lambda judge, row, **_kw: written.append(judge))

    monkeypatch.setattr(postmortems, "list_for_judge", lambda judge: [])
    assert pl.retry_pending_postmortems(data, observation) == 1
    assert written == ["oracle"]

    written.clear()

    def unreadable(judge):
        raise OSError("postmortem file unreadable")

    monkeypatch.setattr(postmortems, "list_for_judge", unreadable)
    pl.retry_pending_postmortems(data, observation)
    assert written == []


def test_pick_mirror_keeps_sibling_soul_map_key(tmp_path, monkeypatch):
    path = _primed_soul_map(tmp_path, monkeypatch)

    pl._mirror_pick_to_soul_map(
        {"id": "p1"}, {"id": "p1", "created_at": "2026-07-01T10:00:00Z"}, "day"
    )

    assert _sibling_survives(path)


def test_hold_mirror_keeps_sibling_soul_map_key(tmp_path, monkeypatch):
    path = _primed_soul_map(tmp_path, monkeypatch)
    from internal.learning import trail_events
    monkeypatch.setattr(trail_events, "emit_trail_event", lambda *a, **k: None)

    pl.record_hold_decision(candidate=None, reason="no edge", horizon_type="day")

    with open(path, encoding="utf-8") as fh:
        on_disk = json.load(fh)
    assert on_disk["soul_map_state"]["last_day_hold"]["action"] == "HOLD"
    assert _sibling_survives(path)
