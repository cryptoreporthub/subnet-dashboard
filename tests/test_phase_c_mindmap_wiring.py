"""Phase C — mindmap display wiring (dev signals, judges PM/weights, MI trust, pump snapshots)."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from server import app


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_mindmap_state_includes_phase_c_summaries(client):
    state = client.get("/api/mindmap/state").json()
    assert state["status"] in ("success", "cached")
    summaries = state.get("summaries") or {}
    for key in ("dev_signals", "pump_desk_snapshots"):
        assert key in summaries
        assert summaries[key].get("sentences")


def test_build_mindmap_state_uses_lite_picks_not_scoring(monkeypatch):
    from internal.learning import panel_summaries
    from internal.learning.mindmap_aggregator import build_mindmap_state

    monkeypatch.setattr(
        panel_summaries,
        "summarize_picks",
        lambda: (_ for _ in ()).throw(AssertionError("scoring path must not run")),
    )
    monkeypatch.setattr(
        panel_summaries,
        "summarize_picks_lite",
        lambda: {"text": "lite picks", "sentences": ["lite picks"]},
    )
    monkeypatch.setattr(
        panel_summaries,
        "summarize_council",
        lambda: {"text": "council", "sentences": ["council"]},
    )
    monkeypatch.setattr(
        panel_summaries,
        "summarize_judges",
        lambda: {"text": "judges", "sentences": ["judges"]},
    )
    monkeypatch.setattr(
        panel_summaries,
        "summarize_learning",
        lambda: {"text": "learning", "sentences": ["learning"]},
    )
    for fn in (
        "summarize_pump_guarded",
        "summarize_scenario_guarded",
        "summarize_message_intel_guarded",
        "summarize_pump_tracker_guarded",
        "summarize_pump_ladder_guarded",
        "summarize_dev_signals_guarded",
        "summarize_pump_desk_snapshots_guarded",
    ):
        monkeypatch.setattr(panel_summaries, fn, lambda: None)

    import internal.learning.mindmap_aggregator as agg

    monkeypatch.setattr(agg, "_STATE_CACHE", {"at": 0.0, "payload": None})
    state = build_mindmap_state()
    assert state["summaries"]["picks"]["text"] == "lite picks"


def test_mindmap_state_cache_reuses_payload(monkeypatch):
    import internal.learning.mindmap_aggregator as agg

    calls = {"n": 0}

    def _council():
        calls["n"] += 1
        return {"text": "c", "sentences": ["c"]}

    monkeypatch.setattr(agg, "_STATE_CACHE", {"at": 0.0, "payload": None})
    monkeypatch.setattr(agg, "_STATE_CACHE_TTL", 60.0)

    from internal.learning import panel_summaries

    monkeypatch.setattr(panel_summaries, "summarize_council", _council)
    monkeypatch.setattr(panel_summaries, "summarize_judges", lambda: {"text": "j", "sentences": ["j"]})
    monkeypatch.setattr(panel_summaries, "summarize_learning", lambda: {"text": "l", "sentences": ["l"]})
    monkeypatch.setattr(panel_summaries, "summarize_picks_lite", lambda: {"text": "p", "sentences": ["p"]})
    for fn in (
        "summarize_pump_guarded",
        "summarize_scenario_guarded",
        "summarize_message_intel_guarded",
        "summarize_pump_tracker_guarded",
        "summarize_pump_ladder_guarded",
        "summarize_dev_signals_guarded",
        "summarize_pump_desk_snapshots_guarded",
    ):
        monkeypatch.setattr(panel_summaries, fn, lambda: None)

    agg.build_mindmap_state()
    agg.build_mindmap_state()
    assert calls["n"] == 1


def test_summarize_judges_mentions_postmortems_and_weights():
    from internal.learning.panel_summaries import summarize_judges

    with patch("internal.judges.postmortems.all_postmortems", return_value={"oracle": [{"id": 1}], "echo": [], "pulse": []}):
        with patch(
            "internal.judges.weights.normalized_judge_weights",
            return_value={"oracle": 0.4, "echo": 0.3, "pulse": 0.3},
        ):
            out = summarize_judges()
    text = out.get("text", "").lower()
    assert "post-mortem" in text or "postmortem" in text.replace("-", "")
    assert "weight" in text


def test_summarize_dev_signals_from_cache(tmp_path, monkeypatch):
    cache = tmp_path / "dev_radar_cache.json"
    cache.write_text(
        json.dumps(
            {
                "updated_at": "2026-08-02T00:00:00Z",
                "subnets": {
                    "7": {
                        "velocity_score": 88.0,
                        "gap_score": 72.0,
                        "gap_signal": "dev_ahead_of_price",
                        "commits_7d": 14,
                        "synced_at": "2026-08-02T00:00:00Z",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("internal.dev_radar.github_sync.CACHE_PATH", str(cache))
    from internal.dev_radar.summary import summarize_dev_signals

    out = summarize_dev_signals()
    assert "dev" in out["text"].lower()
    assert "gap" in out["text"].lower() or "ahead" in out["text"].lower()


def test_dev_signals_trail_emits_gap_events(tmp_path, monkeypatch):
    cache = tmp_path / "dev_radar_cache.json"
    cache.write_text(
        json.dumps(
            {
                "updated_at": "2026-08-02T00:00:00Z",
                "subnets": {
                    "12": {
                        "gap_signal": "dev_ahead_of_price",
                        "gap_score": 65.0,
                        "synced_at": "2026-08-02T00:00:00Z",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("internal.dev_radar.github_sync.CACHE_PATH", str(cache))
    from internal.learning.mindmap_aggregator import _trail_from_dev_signals

    events = _trail_from_dev_signals()
    assert len(events) == 1
    assert events[0]["netuid"] == 12
    assert events[0]["signal"] == "dev_radar"


def test_summarize_message_intel_author_trust(intel_env):
    from internal.message_intel.summary import summarize_message_intel
    from internal.message_intel.store import get_db

    db = get_db()
    db.increment_author_reliability("u1", "Alice", correct=True)
    db.increment_author_reliability("u1", "Alice", correct=True)
    db.increment_author_reliability("u2", "Bob", correct=False)

    summary = summarize_message_intel()
    assert "author trust" in summary["text"].lower() or "alice" in summary["text"].lower()


@pytest.fixture
def intel_env(tmp_path, monkeypatch):
    db_path = str(tmp_path / "message_intel.db")
    monkeypatch.setenv("MESSAGE_INTEL_DB", db_path)
    from internal.message_intel import store

    store.reset_db_cache()
    yield {"db_path": db_path}
