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
