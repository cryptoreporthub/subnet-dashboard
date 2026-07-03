import json
import os
import tempfile

import pytest
from fastapi.testclient import TestClient

from internal.council import daily_pick_engine
from server import app


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def isolated_daily_picks(tmp_path):
    """Keep daily-pick persistence out of the repo data directory."""
    original_path = daily_pick_engine.DAILY_PICKS_PATH
    daily_pick_engine.DAILY_PICKS_PATH = str(tmp_path / "daily_picks.json")
    yield
    daily_pick_engine.DAILY_PICKS_PATH = original_path


def test_top_pick_hour_returns_picks_list(client):
    response = client.get("/api/top-pick/hour")
    assert response.status_code == 200
    data = response.json()
    assert "picks" in data
    assert isinstance(data["picks"], list)
    assert len(data["picks"]) <= 3

    for pick in data["picks"]:
        assert "subnet" in pick
        assert set(pick["subnet"].keys()) >= {"netuid", "name", "symbol"}
        assert "score" in pick
        assert "confidence" in pick
        assert "expert_contributions" in pick
        assert "scenario_tags" in pick
        assert "signals" in pick
        assert set(pick["signals"].keys()) >= {
            "price_change_24h",
            "price_change_7d",
            "emission",
            "apy",
            "volume",
        }
        assert pick.get("action") == "long"


def test_daily_pick_returns_structured_payload(client):
    response = client.get("/api/daily-pick")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "date" in data
    assert "timestamp_utc" in data
    assert "action" in data
    assert "regime" in data
    assert "rotation_summary" in data

    if data["action"] == "HOLD":
        assert data["pick"] is None
        assert "reason" in data
    else:
        assert data["pick"] is not None
        assert "subnet" in data["pick"]
        assert "final_confidence" in data["pick"]


def test_daily_pick_is_deterministic_and_cached(client):
    r1 = client.get("/api/daily-pick").json()
    r2 = client.get("/api/daily-pick").json()
    assert r1["date"] == r2["date"]
    assert r1["action"] == r2["action"]
    assert r1["timestamp_utc"] == r2["timestamp_utc"]


def test_daily_pick_engine_handles_empty_subnets():
    with tempfile.TemporaryDirectory() as tmp:
        daily_pick_engine.DAILY_PICKS_PATH = os.path.join(tmp, "daily_picks.json")
        payload = daily_pick_engine.get_or_create_today_pick([], {})
        assert payload["action"] == "HOLD"
        assert payload["pick"] is None
        assert "No subnets available" in payload["reason"]
        assert payload["regime"] == "neutral"


def test_load_past_picks_limit():
    with tempfile.TemporaryDirectory() as tmp:
        daily_pick_engine.DAILY_PICKS_PATH = os.path.join(tmp, "daily_picks.json")
        records = [{"date": f"2026-06-{20 + i:02d}"} for i in range(5)]
        daily_pick_engine._save(records)
        assert len(daily_pick_engine.load_past_picks(limit=3)) == 3
