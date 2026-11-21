"""Replaying a resolved prediction must not double-count a judge's closed position or nudge."""

from __future__ import annotations

import json

import pytest

import internal.judges.portfolios as portfolios
import internal.judges.tracker as tracker
import internal.judges.postmortems as postmortems
import internal.judges.weights as judge_weights


@pytest.fixture
def portfolio_path(tmp_path, monkeypatch):
    path = tmp_path / "judge_portfolios.json"
    monkeypatch.setattr(portfolios, "PORTFOLIOS_PATH", str(path))
    return path


def _prediction() -> dict:
    return {
        "id": "pred-replay-1",
        "netuid": 7,
        "name": "Replay Test",
        "direction": "up",
        "predicted_pct": 2.0,
        "reference_price": 100.0,
        "resolved_price": 110.0,
        "horizon_hours": 1,
        "outcome": "hit",
        "correct": True,
        "created_at": "2026-07-01T00:00:00Z",
    }


def test_replayed_resolution_closes_once_and_nudges_once(portfolio_path, monkeypatch):
    nudges: list[str] = []
    monkeypatch.setattr(
        judge_weights, "nudge_judge", lambda name, *_a, **_k: nudges.append(name)
    )
    prediction = _prediction()
    for judge in tracker.all_judges():
        judge.open_position(prediction, size=1.0)

    tracker.on_prediction_resolved(prediction)
    tracker.on_prediction_resolved(prediction)

    data = json.loads(portfolio_path.read_text(encoding="utf-8"))
    for judge_name in ("oracle", "echo", "pulse"):
        closed = data[judge_name]["closed_positions"]
        assert [c["id"] for c in closed] == ["pred-replay-1"], judge_name
    assert len(nudges) == len(tracker.all_judges())


def test_replay_close_clears_stale_open_position(portfolio_path):
    """A second close with the same id must not leave a ghost open row."""
    prediction = _prediction()
    portfolios.open_position("oracle", prediction, size=1.0)
    assert portfolios.close_position("oracle", prediction, actual_pct=10.0, outcome="hit")
    portfolios.open_position("oracle", prediction, size=1.0)
    assert portfolios.close_position("oracle", prediction, actual_pct=10.0, outcome="hit") is None
    oracle = json.loads(portfolio_path.read_text(encoding="utf-8"))["oracle"]
    assert len(oracle["closed_positions"]) == 1
    assert not any(p.get("id") == prediction["id"] for p in oracle["open_positions"])


def test_close_position_returns_none_on_replay(portfolio_path):
    prediction = _prediction()
    portfolios.open_position("oracle", prediction, size=1.0)

    first = portfolios.close_position("oracle", prediction, actual_pct=10.0, outcome="hit")
    second = portfolios.close_position("oracle", prediction, actual_pct=10.0, outcome="hit")

    assert isinstance(first, dict)
    assert second is None
    closed = json.loads(portfolio_path.read_text(encoding="utf-8"))["oracle"]["closed_positions"]
    assert len(closed) == 1


def test_replayed_wrong_pick_records_one_postmortem_per_judge(portfolio_path, monkeypatch, tmp_path):
    monkeypatch.setattr(postmortems, "POSTMORTEMS_DIR", str(tmp_path / "postmortems"))
    monkeypatch.setattr(judge_weights, "nudge_judge", lambda *_a, **_k: None)
    prediction = {
        **_prediction(),
        "id": "pred-replay-wrong-1",
        "outcome": "miss",
        "correct": False,
        "resolved_price": 95.0,
    }
    for judge in tracker.all_judges():
        judge.open_position(prediction, size=1.0)

    tracker.on_prediction_resolved(prediction)
    tracker.on_prediction_resolved(prediction)

    for judge in tracker.all_judges():
        entries = postmortems.list_for_judge(judge.name)
        assert len(entries) == 1, judge.name


def test_regrading_same_prediction_id_keeps_latest_actual(tmp_path, monkeypatch):
    monkeypatch.setattr(postmortems, "POSTMORTEMS_DIR", str(tmp_path / "postmortems"))
    prediction = {"id": "pred-regrade-1", "netuid": 7, "name": "SN7", "direction": "up", "predicted_pct": 3.0}

    first = postmortems.record("oracle", prediction, actual_pct=-2.0)
    postmortems.record("oracle", prediction, actual_pct=-5.0)

    entries = [e for e in postmortems.list_for_judge("oracle") if e["prediction_id"] == "pred-regrade-1"]
    assert len(entries) == 1
    assert entries[0]["actual_pct"] == -5.0
    assert entries[0]["created_at"] == first["created_at"]


def test_recording_same_grade_again_leaves_file_unchanged(tmp_path, monkeypatch):
    monkeypatch.setattr(postmortems, "POSTMORTEMS_DIR", str(tmp_path / "postmortems"))
    prediction = {"id": "pred-regrade-2", "netuid": 7, "name": "SN7", "direction": "up", "predicted_pct": 3.0}
    postmortems.record("oracle", prediction, actual_pct=-5.0)

    path = postmortems._path("oracle")
    before = open(path, "rb").read()
    postmortems.record("oracle", prediction, actual_pct=-5.0)

    assert open(path, "rb").read() == before
