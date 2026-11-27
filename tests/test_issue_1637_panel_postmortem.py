"""#1637: corrupt postmortem replay log + load_weights guards in panel summaries."""

from __future__ import annotations

import logging

import pytest

import internal.judges.postmortems as postmortems
import internal.judges.tracker as tracker
from internal.council import weights as council_weights
from internal.learning import panel_summaries
from internal.learning.mindmap_aggregator import build_mindmap_state

_COUNCIL_NOT_LOADED = (
    "Council expert weights are not loaded yet; all experts sit at default influence."
)
_LEARNING_WEIGHTS_UNAVAILABLE = (
    "Council expert weights could not load; learned-weight details are omitted from "
    "this learning summary."
)


@pytest.fixture
def pm_dir(tmp_path, monkeypatch):
    directory = tmp_path / "postmortems"
    directory.mkdir()
    monkeypatch.setattr(postmortems, "POSTMORTEMS_DIR", str(directory))
    return directory


def test_postmortem_corrupt_file_logs_error_and_returns_false(pm_dir, caplog):
    path = pm_dir / "oracle.json"
    path.write_bytes(b"not-json")
    with caplog.at_level(logging.ERROR):
        seen = tracker._postmortem_already_recorded("oracle", "pred-1637")
    assert seen is False
    errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert len(errors) == 1
    assert errors[0].name == tracker.logger.name
    assert "oracle" in errors[0].getMessage()
    assert "pred-1637" in errors[0].getMessage()
    assert str(path) in errors[0].getMessage()


def test_summarize_council_survives_concurrent_weight_update(monkeypatch):
    def _boom():
        raise council_weights.ConcurrentWeightUpdate("stale weight map")

    monkeypatch.setattr(council_weights, "load_weights", _boom)
    out = panel_summaries.summarize_council()
    assert isinstance(out, dict)
    assert _COUNCIL_NOT_LOADED in out.get("text", "")
    assert _COUNCIL_NOT_LOADED in out.get("sentences", [])[0]


def test_summarize_learning_survives_concurrent_weight_update(monkeypatch):
    def _boom():
        raise council_weights.ConcurrentWeightUpdate("stale weight map")

    monkeypatch.setattr(council_weights, "load_weights", _boom)
    out = panel_summaries.summarize_learning()
    assert isinstance(out, dict)
    text = out.get("text", "")
    assert _LEARNING_WEIGHTS_UNAVAILABLE in text
    assert "strongest learned weight" not in text.lower()


def test_build_mindmap_state_survives_concurrent_weight_update(monkeypatch):
    def _boom():
        raise council_weights.ConcurrentWeightUpdate("stale weight map")

    monkeypatch.setattr(council_weights, "load_weights", _boom)
    state = build_mindmap_state()
    assert isinstance(state, dict)
    summaries = state.get("summaries") or {}
    assert "council" in summaries and "learning" in summaries
    assert _COUNCIL_NOT_LOADED in (summaries["council"].get("text") or "")
    assert _LEARNING_WEIGHTS_UNAVAILABLE in (summaries["learning"].get("text") or "")