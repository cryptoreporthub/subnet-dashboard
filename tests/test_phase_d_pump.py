"""Phase D — pump ladder classification, transitions, Soul-Map + trail."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from internal.pump.engine import classify_signals, compute_composite_score, raw_phase_from_score
from internal.pump.state import load_state, save_state, scan_all_subnets, transition_subnet
from server import app


@pytest.fixture
def ladder_env(tmp_path, monkeypatch):
    state_path = str(tmp_path / "pump_ladder.json")
    soul_path = str(tmp_path / "soul_map.json")
    tmp_path.joinpath("soul_map.json").write_text(
        json.dumps(
            {
                "adversarial_state": {"council_weights": {"quant": 1.0, "hype": 1.0, "dark_horse": 1.0, "technical": 1.0}},
                "soul_map_state": {"learning_trail": []},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("PUMP_LADDER_STATE_PATH", state_path)
    monkeypatch.setenv("SOUL_MAP_PATH", soul_path)
    monkeypatch.setenv("PUMP_LADDER_LOCK_MINUTES", "0")
    from internal.council import weights
    from internal.pump import constants
    from internal.pump import state as pump_state

    monkeypatch.setattr(weights, "SOUL_MAP_PATH", soul_path)
    monkeypatch.setattr(constants, "STATE_PATH", state_path)
    monkeypatch.setattr(constants, "PHASE_LOCK_MINUTES", 0)
    yield {"state_path": state_path, "soul_path": soul_path}


@pytest.fixture
def client(ladder_env):
    with TestClient(app) as c:
        yield c


def test_classify_high_volume_bullish():
    signals = {
        "netuid": 7,
        "name": "SN7",
        "price_change_24h": 0.12,
        "momentum_1h": 0.05,
        "volume_intensity": 0.9,
        "buy_ratio": 0.72,
        "chatter_intensity": 0.4,
        "scenario_tag": "risk_on",
    }
    score = compute_composite_score(signals)
    assert score >= 0.55
    result = classify_signals(signals)
    assert result["suggested_phase"] in ("ACCUMULATING", "PUMPING")


def test_upward_transition_capped_one_rung(ladder_env):
    """From STIRRING, a spike cannot skip directly to PUMPING in one tick."""
    state = {
        "subnets": {
            "5": {
                "netuid": 5,
                "name": "Ramp",
                "phase": "STIRRING",
                "since": "2026-07-11T00:00:00Z",
                "composite_score": 0.25,
                "transitions": [],
            }
        },
        "meta": {},
    }
    hot = {
        "netuid": 5,
        "name": "Ramp",
        "price_change_24h": 0.15,
        "momentum_1h": 0.06,
        "volume_intensity": 0.95,
        "buy_ratio": 0.8,
        "chatter_intensity": 0.5,
    }
    event, changed = transition_subnet(state, hot)
    assert changed
    assert event["to_phase"] == "ACCUMULATING"
    assert state["subnets"]["5"]["phase"] == "ACCUMULATING"


def test_scan_emits_soul_map_and_trail(ladder_env):
    subnets = [
        {
            "netuid": 1,
            "name": "Alpha",
            "price_change_24h": 0.10,
            "volume": 50000,
            "emission": 2.0,
            "buy_volume_24h": 8000,
            "sell_volume_24h": 2000,
        },
        {
            "netuid": 2,
            "name": "Beta",
            "price_change_24h": 0.02,
            "volume": 1000,
            "emission": 1.0,
            "buy_volume_24h": 500,
            "sell_volume_24h": 500,
        },
    ]

    state = {"version": "1.0", "subnets": {}, "meta": {}}
    with patch("internal.pump.state.fetch_all_subnet_signals", return_value=[
        __import__("internal.pump.signals", fromlist=["build_subnet_signals"]).build_subnet_signals(s)
        for s in subnets
    ]):
        result = scan_all_subnets(state)

    assert result["ok"] is True
    assert result["scanned"] == 2
    assert len(result.get("transitions") or []) >= 1
    assert (result.get("soul_map") or {}).get("disposition_updates", 0) >= 1

    from internal.council import weights

    soul = json.loads(open(weights.SOUL_MAP_PATH, encoding="utf-8").read())
    sms = soul.get("soul_map_state") or {}
    assert sms.get("pump_dispositions")
    trail = sms.get("learning_trail") or []
    assert trail


def test_summarize_from_live_state(ladder_env):
    state = load_state(ladder_env["state_path"])
    state["subnets"] = {
        "1": {
            "netuid": 1,
            "name": "Alpha",
            "phase": "PUMPING",
            "composite_score": 0.72,
            "since": "2026-07-11T00:00:00Z",
            "transitions": [],
        }
    }
    state["meta"] = {
        "tracked_subnets": 1,
        "phase_counts": {"PUMPING": 1},
        "last_scan_at": "2026-07-11T01:00:00Z",
        "last_transition_count": 1,
    }
    save_state(state, ladder_env["state_path"])

    from internal.pump.summary import summarize_pump

    summary = summarize_pump()
    assert summary["sentences"]
    assert "PUMPING" in summary["text"] or "pump ladder" in summary["text"].lower()


def test_api_pump_ladder_state(client, ladder_env):
    with patch("internal.pump.state.fetch_all_subnet_signals", return_value=[]):
        resp = client.get("/api/pump-ladder/state")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "success"
    assert "summary" in body


def test_cooling_from_pumping():
    phase = raw_phase_from_score(0.48, was_pumping=True)
    assert phase == "COOLING"


def test_engine_api_aliases_for_tracker_adapter(ladder_env):
    from internal.pump.engine import build_ladder_snapshot as engine_build
    from internal.pump.state import (
        build_ladder_snapshot,
        get_ladder,
        get_top_movers,
        save_state,
    )

    save_state(
        {
            "subnets": {
                "7": {
                    "netuid": 7,
                    "name": "Seven",
                    "phase": "ACCUMULATING",
                    "composite_score": 0.55,
                    "transitions": [
                        {
                            "time": "2026-07-11T01:00:00Z",
                            "from_phase": "STIRRING",
                            "to_phase": "ACCUMULATING",
                            "composite_score": 0.55,
                        }
                    ],
                }
            },
            "meta": {},
        },
        ladder_env["state_path"],
    )

    ladder = get_ladder(ladder_env["state_path"])
    assert ladder["source"] == "internal.pump.state"
    assert ladder["subnets"][0]["current_phase"] == "ACCUMULATING"

    assert build_ladder_snapshot(ladder_env["state_path"])["count"] == 1
    assert engine_build(ladder_env["state_path"])["count"] == 1

    movers = get_top_movers(limit=5, path=ladder_env["state_path"])
    assert movers["status"] == "success"
    assert movers["count"] == 1
    assert movers["movers"][0]["to_phase"] == "ACCUMULATING"

    empty = get_top_movers(limit=5, path=ladder_env["state_path"])
    assert empty["movers"]  # still one transition

    save_state({"subnets": {}, "meta": {}}, ladder_env["state_path"])
    assert get_top_movers(limit=5, path=ladder_env["state_path"])["movers"] == []


def test_pump_tracker_uses_engine_not_legacy(client, ladder_env, monkeypatch):
    from internal.pump import constants as pump_constants
    from internal.pump import state as pump_state

    monkeypatch.setattr(pump_constants, "STATE_PATH", ladder_env["state_path"])
    pump_state.save_state(
        {
            "subnets": {
                "1": {
                    "netuid": 1,
                    "name": "One",
                    "phase": "STIRRING",
                    "composite_score": 0.3,
                    "transitions": [],
                }
            },
            "meta": {"last_scan_at": "2026-07-11T01:00:00Z"},
        },
        ladder_env["state_path"],
    )

    ladder = client.get("/api/pump-tracker/ladder").json()
    assert ladder["status"] == "success"
    assert ladder.get("source") == "internal.pump.state"
    assert ladder["subnets"][0]["current_phase"] == "STIRRING"

    summary = client.get("/api/pump-tracker/summary").json()
    assert summary["status"] == "success"
    assert "STIRRING" in summary["summary"]["text"] or "pump ladder" in summary["summary"]["text"].lower()
