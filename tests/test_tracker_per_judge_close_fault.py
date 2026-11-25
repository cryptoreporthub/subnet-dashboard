"""One judge's unobservable portfolio must not stop the other judges from closing."""

from __future__ import annotations

import json

import pytest

import internal.judges.portfolios as portfolios
import internal.judges.postmortems as postmortems
import internal.judges.tracker as tracker
import internal.judges.weights as judge_weights

JUDGES = ("oracle", "echo", "pulse")


@pytest.fixture
def book(tmp_path, monkeypatch):
    path = tmp_path / "judge_portfolios.json"
    monkeypatch.setattr(portfolios, "PORTFOLIOS_PATH", str(path))
    monkeypatch.setattr(postmortems, "POSTMORTEMS_DIR", str(tmp_path / "postmortems"))
    monkeypatch.setattr(judge_weights, "nudge_judge", lambda *_a, **_k: None)
    return path


def _prediction(*, wrong: bool) -> dict:
    return {
        "id": "pred-fault-1",
        "netuid": 7,
        "name": "Fault Test",
        "direction": "up",
        "predicted_pct": 2.0,
        "reference_price": 100.0,
        "resolved_price": 95.0 if wrong else 110.0,
        "horizon_hours": 1,
        "outcome": "miss" if wrong else "hit",
        "correct": not wrong,
        "created_at": "2026-07-01T00:00:00Z",
    }


def _fail_oracle_close(monkeypatch, exc: Exception) -> None:
    real_close = portfolios.close_position

    def close(judge_name, *args, **kwargs):
        if judge_name == "oracle":
            raise exc
        return real_close(judge_name, *args, **kwargs)

    monkeypatch.setattr(portfolios, "close_position", close)


def _open_all(prediction: dict) -> None:
    for judge in tracker.all_judges():
        judge.open_position(prediction, size=1.0)


def _closed_ids(book, judge_name: str) -> list:
    data = json.loads(book.read_text(encoding="utf-8"))
    return [c["id"] for c in data[judge_name]["closed_positions"]]


def test_lock_timeout_on_one_judge_does_not_abort_the_others(book, monkeypatch):
    prediction = _prediction(wrong=False)
    _open_all(prediction)
    _fail_oracle_close(
        monkeypatch, portfolios.PortfolioLockTimeout("timed out waiting for portfolios mutex")
    )

    summary = tracker.on_prediction_resolved(prediction)

    assert summary["portfolios_unobservable"] is True
    assert summary["judges"]["oracle"]["closed"] is None
    assert _closed_ids(book, "echo") == ["pred-fault-1"]
    assert _closed_ids(book, "pulse") == ["pred-fault-1"]
    assert _closed_ids(book, "oracle") == []


def test_unreadable_judge_does_not_suppress_later_judges_postmortems(book, monkeypatch):
    prediction = _prediction(wrong=True)
    _open_all(prediction)
    _fail_oracle_close(monkeypatch, portfolios.PortfolioUnreadable("torn book"))

    summary = tracker.on_prediction_resolved(prediction)

    assert summary["portfolios_unobservable"] is True
    assert summary["judges"]["oracle"]["postmortem"] is None
    for name in ("echo", "pulse"):
        assert summary["judges"][name]["closed"] is not None, name
        entries = postmortems.list_for_judge(name)
        assert [e["prediction_id"] for e in entries] == ["pred-fault-1"], name
