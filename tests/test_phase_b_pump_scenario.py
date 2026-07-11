"""Phase B — Pump + Scenario summaries and trail subscribers (Agent B)."""

from __future__ import annotations

import json

import pytest

from internal.analytics.pump_feed import sync_pump_trail_events
from internal.analytics.pump_summary import summarize_pump
from internal.analytics.scenario_feed import sync_scenario_trail_events
from internal.analytics.scenario_state import load_scenario_snapshot
from internal.analytics.scenario_summary import summarize_scenario
from internal.analytics.trail_cursor import seen_scenario_ids


def test_summarize_scenario_from_live_shape():
    state = {
        "scenarios": [
            {
                "id": "sc_test",
                "name": "SubnetX",
                "regime": "volatile",
                "features": {
                    "rsi": "overbought",
                    "volume": "low",
                    "volatility": 12.5,
                    "direction": "up",
                    "expert": "technical",
                },
                "outcome": "correct",
            }
        ],
        "stats": {
            "total": 1,
            "by_regime": {"volatile": 1, "bull": 0, "bear": 0, "neutral": 0},
            "accuracy": {"volatile": 1.0},
        },
        "meta": {"last_updated": "2026-07-11T00:00:00Z"},
    }
    text = summarize_scenario(state)
    assert "volatile" in text
    assert "overbought" in text
    assert len(text.split(".")) >= 3


def test_summarize_pump_phase_distribution():
    payload = {
        "status": "success",
        "data": {
            "subnets": [
                {
                    "netuid": 1,
                    "name": "Alpha",
                    "current_phase": "EARLY",
                    "pump_proneness": 72,
                    "final_score": 0.55,
                },
                {
                    "netuid": 2,
                    "name": "Beta",
                    "current_phase": "SELL",
                    "pump_proneness": 88,
                    "final_score": 0.91,
                },
            ],
            "meta": {
                "tracked_subnets": 2,
                "total_cycles": 5,
                "avg_proneness": 80.0,
            },
        },
    }
    text = summarize_pump(payload)
    assert "EARLY" in text or "early" in text.lower()
    assert "SELL" in text or "sell" in text.lower()
    assert "Alpha" in text


def test_scenario_trail_emits_on_new_snapshot(tmp_path, monkeypatch):
    scenario_path = tmp_path / "scenario_memory.json"
    soul_path = tmp_path / "soul_map.json"
    cursor_path = tmp_path / "trail_cursor.json"
    soul_path.write_text(
        json.dumps({"soul_map_state": {"learning_trail": []}, "adversarial_state": {}}),
        encoding="utf-8",
    )
    cursor_path.write_text(
        json.dumps({"seen_scenario_ids": ["sc_prior"], "pump_phases": {}}),
        encoding="utf-8",
    )
    scenario_path.write_text(
        json.dumps(
            {
                "scenarios": [
                    {
                        "id": "sc_new_1",
                        "name": "Minos",
                        "regime": "bull",
                        "features": {"rsi": "neutral", "volume": "high"},
                    }
                ],
                "regimes": {"bull": ["sc_new_1"]},
                "meta": {},
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "internal.analytics.scenario_state.SCENARIO_MEMORY_PATH",
        str(scenario_path),
    )
    monkeypatch.setattr(
        "internal.analytics.trail_cursor.CURSOR_PATH",
        str(cursor_path),
    )
    import internal.council.weights as weights_mod

    monkeypatch.setattr(weights_mod, "SOUL_MAP_PATH", str(soul_path))

    emitted = sync_scenario_trail_events()
    assert emitted == 1
    assert "sc_new_1" in seen_scenario_ids()

    soul = json.loads(soul_path.read_text(encoding="utf-8"))
    trail = soul["soul_map_state"]["learning_trail"]
    assert any(e.get("event_type") == "scenario_tagged" for e in trail)

    # Second sync should not duplicate
    assert sync_scenario_trail_events() == 0


def test_pump_trail_emits_on_phase_transition(tmp_path, monkeypatch):
    soul_path = tmp_path / "soul_map.json"
    cursor_path = tmp_path / "trail_cursor.json"
    soul_path.write_text(
        json.dumps({"soul_map_state": {"learning_trail": []}, "adversarial_state": {}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "internal.analytics.trail_cursor.CURSOR_PATH",
        str(cursor_path),
    )
    import internal.council.weights as weights_mod

    monkeypatch.setattr(weights_mod, "SOUL_MAP_PATH", str(soul_path))

    payload = {
        "data": {
            "subnets": [
                {
                    "netuid": 7,
                    "name": "Gamma",
                    "current_phase": "EARLY",
                    "pump_score": 0.4,
                    "final_score": 0.5,
                    "pump_proneness": 60,
                }
            ]
        }
    }
    emitted = sync_pump_trail_events(payload)
    assert emitted == 1
    soul = json.loads(soul_path.read_text(encoding="utf-8"))
    trail = soul["soul_map_state"]["learning_trail"]
    assert any(e.get("event_type") == "signal_triggered" for e in trail)


def test_load_scenario_snapshot_no_council_import():
    snap = load_scenario_snapshot(path="/nonexistent/path.json")
    assert snap["status"] == "ok"
    assert snap["scenarios"] == []


def test_pump_analytics_includes_summary():
    from fastapi.testclient import TestClient

    from server import app

    with TestClient(app) as client:
        resp = client.get("/api/pump-analytics")
    assert resp.status_code == 200
    body = resp.json()
    assert "summary" in body
    assert isinstance(body["summary"], str)
    assert len(body["summary"]) > 20
    assert "scenario_summary" in body
