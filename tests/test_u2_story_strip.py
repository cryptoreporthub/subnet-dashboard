"""§17.U2 — pick story strip."""

from __future__ import annotations

import json

import pytest

from internal.analytics.story_strip import build_story_strip
from fastapi.testclient import TestClient

from server import app


def test_build_story_strip_honest_empty(tmp_path, monkeypatch):
    preds = tmp_path / "predictions.json"
    preds.write_text(json.dumps({"predictions": [], "resolved": []}), encoding="utf-8")
    import internal.learning.predictions_store as ps

    monkeypatch.setattr(ps, "PREDICTIONS_PATH", str(preds))
    strip = build_story_strip(limit=5)
    assert strip["data_available"] is False
    assert strip["reason"] == "no_resolved_outcomes"
    assert strip["items"] == []


def test_build_story_strip_labels_outcomes(tmp_path, monkeypatch):
    preds = tmp_path / "predictions.json"
    preds.write_text(
        json.dumps(
            {
                "predictions": [],
                "resolved": [
                    {
                        "id": "a1",
                        "netuid": 7,
                        "name": "Sub7",
                        "direction": "up",
                        "predicted_pct": 5.0,
                        "actual_pct": 6.0,
                        "status": "resolved",
                        "correct": True,
                    },
                    {
                        "id": "a2",
                        "netuid": 3,
                        "name": "Sub3",
                        "direction": "down",
                        "predicted_pct": -4.0,
                        "actual_pct": 2.0,
                        "status": "resolved",
                        "correct": False,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    import internal.learning.predictions_store as ps

    monkeypatch.setattr(ps, "PREDICTIONS_PATH", str(preds))
    strip = build_story_strip(limit=5)
    assert strip["data_available"] is True
    assert len(strip["items"]) == 2
    assert strip["items"][0]["outcome"] == "wrong"
    assert strip["items"][0]["share_page_url"] == "/share/call/a2"
    assert strip["items"][1]["outcome"] == "correct"
    assert strip["items"][1]["share_page_url"] == "/share/call/a1"
    assert strip["stats"]["correct"] == 1
    assert strip["stats"]["wrong"] == 1


def test_index_renders_story_strip_section():
    with TestClient(app) as client:
        html = client.get("/").text
    assert 'id="section-story-strip"' in html
    assert "story-strip" in html
