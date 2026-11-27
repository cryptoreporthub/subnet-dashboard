"""#1637: corrupt postmortem replay log + load_weights guards in panel summaries."""

from __future__ import annotations

import logging

import pytest

import internal.judges.postmortems as postmortems
import internal.judges.tracker as tracker
from internal.council import weights as council_weights
from internal.learning import mindmap_aggregator as mindmap_agg
from internal.learning import panel_summaries
from internal.learning.mindmap_aggregator import build_mindmap_state

_COUNCIL_EMPTY = (
    "Council expert weights are not loaded yet; all experts sit at default influence."
)
_COUNCIL_LOAD_ERROR = (
    "Council expert weights could not load right now; expert influence is not shown."
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


def test_mindmap_state_cache_not_warmed_by_prior_test():
    """Module-order isolation: prior tests must not leave a warm mindmap payload."""
    assert mindmap_agg._STATE_CACHE.get("payload") is None


@pytest.fixture(autouse=True)
def reset_mindmap_state_cache():
    prior = dict(mindmap_agg._STATE_CACHE)
    mindmap_agg._STATE_CACHE.clear()
    mindmap_agg._STATE_CACHE.update({"at": 0.0, "payload": None})
    try:
        yield
    finally:
        mindmap_agg._STATE_CACHE.clear()
        mindmap_agg._STATE_CACHE.update(prior)


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


def test_summarize_council_survives_concurrent_weight_update(monkeypatch, caplog):
    def _boom():
        raise council_weights.ConcurrentWeightUpdate("stale weight map")

    monkeypatch.setattr(council_weights, "load_weights", _boom)
    with caplog.at_level(logging.WARNING):
        out = panel_summaries.summarize_council()
    assert isinstance(out, dict)
    text = out.get("text", "")
    assert _COUNCIL_LOAD_ERROR in text
    assert _COUNCIL_EMPTY not in text
    assert "default influence" not in text.lower()
    warns = [
        r
        for r in caplog.records
        if r.levelno == logging.WARNING and r.name == panel_summaries.logger.name
    ]
    assert len(warns) == 1
    assert warns[0].exc_info is not None


def test_summarize_council_typeerror_from_load_weights_propagates(monkeypatch):
    def _boom():
        raise TypeError("programmer error")

    monkeypatch.setattr(council_weights, "load_weights", _boom)
    with pytest.raises(TypeError, match="programmer error"):
        panel_summaries.summarize_council()


def test_summarize_learning_survives_concurrent_weight_update(monkeypatch, caplog):
    def _boom():
        raise council_weights.ConcurrentWeightUpdate("stale weight map")

    monkeypatch.setattr(council_weights, "load_weights", _boom)
    with caplog.at_level(logging.WARNING):
        out = panel_summaries.summarize_learning()
    assert isinstance(out, dict)
    text = out.get("text", "")
    assert _LEARNING_WEIGHTS_UNAVAILABLE in text
    assert "strongest learned weight" not in text.lower()
    assert "correct" in text.lower() and "wrong" in text.lower()
    warns = [
        r
        for r in caplog.records
        if r.levelno == logging.WARNING and r.name == panel_summaries.logger.name
    ]
    assert len(warns) == 1
    assert warns[0].exc_info is not None


def test_summarize_learning_empty_weights_uses_not_loaded_copy(monkeypatch):
    monkeypatch.setattr(council_weights, "load_weights", lambda: {})
    out = panel_summaries.summarize_learning()
    text = out.get("text", "")
    assert _COUNCIL_EMPTY in text
    assert _LEARNING_WEIGHTS_UNAVAILABLE not in text
    assert "strongest learned weight" not in text.lower()


def test_summarize_learning_typeerror_from_load_weights_propagates(monkeypatch):
    def _boom():
        raise TypeError("programmer error")

    monkeypatch.setattr(council_weights, "load_weights", _boom)
    with pytest.raises(TypeError, match="programmer error"):
        panel_summaries.summarize_learning()


def test_mindmap_cache_masks_load_failure_without_reset(monkeypatch):
    warm = build_mindmap_state()
    warm_council = (warm.get("summaries") or {}).get("council", {}).get("text", "")
    assert warm_council
    assert _COUNCIL_LOAD_ERROR not in warm_council

    def _boom():
        raise council_weights.ConcurrentWeightUpdate("stale weight map")

    monkeypatch.setattr(council_weights, "load_weights", _boom)
    cached = build_mindmap_state()
    cached_council = (cached.get("summaries") or {}).get("council", {}).get("text", "")
    assert cached_council == warm_council
    assert _COUNCIL_LOAD_ERROR not in cached_council


def test_build_mindmap_state_survives_concurrent_weight_update(monkeypatch):
    def _boom():
        raise council_weights.ConcurrentWeightUpdate("stale weight map")

    monkeypatch.setattr(council_weights, "load_weights", _boom)
    state = build_mindmap_state()
    assert isinstance(state, dict)
    summaries = state.get("summaries") or {}
    assert "council" in summaries and "learning" in summaries
    assert _COUNCIL_LOAD_ERROR in (summaries["council"].get("text") or "")
    assert _LEARNING_WEIGHTS_UNAVAILABLE in (summaries["learning"].get("text") or "")