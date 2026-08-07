"""Price snapshot + outcome loop wiring for Telegram message-intel."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from server import app


@pytest.fixture
def intel_env(tmp_path, monkeypatch):
    db_path = str(tmp_path / "message_intel.db")
    monkeypatch.setenv("MESSAGE_INTEL_DB", db_path)
    from internal.message_intel import store

    store.reset_db_cache()
    yield {"db_path": db_path}


@pytest.fixture
def client(intel_env):
    with TestClient(app) as c:
        yield c


def test_status_includes_outcomes_key(client):
    body = client.get("/api/message-intel/status").json()
    assert body["status"] == "success"
    assert "outcomes" in body
    assert "running" in body["outcomes"]


def test_outcome_loop_start_stop(intel_env):
    from internal.message_intel import outcome_loop

    outcome_loop.stop_price_outcome_loop()
    with patch("message_intel.price_tracker.PriceTracker.start_background_checks") as start:
        start.side_effect = lambda interval=300: setattr(
            outcome_loop, "_tracker", MagicMock(_running=True)
        ) or None
        # Call real start but mock PriceTracker class
        with patch("message_intel.price_tracker.PriceTracker") as PT:
            inst = MagicMock()
            inst._running = False

            def _start(interval=300):
                inst._running = True

            inst.start_background_checks.side_effect = _start
            PT.return_value = inst
            assert outcome_loop.start_price_outcome_loop(interval=60) is True
            assert outcome_loop.outcome_loop_status()["running"] is True
            outcome_loop.stop_price_outcome_loop()
            assert outcome_loop.outcome_loop_status()["running"] is False


def test_outcome_loop_cross_process_heartbeat(intel_env, tmp_path, monkeypatch):
    from internal.message_intel import outcome_loop

    hb = tmp_path / "outcome_hb.json"
    monkeypatch.setenv("MESSAGE_INTEL_OUTCOME_HEARTBEAT", str(hb))
    outcome_loop.stop_price_outcome_loop()
    outcome_loop._touch_outcome_heartbeat()
    assert outcome_loop.outcome_loop_status()["running"] is True
    outcome_loop.stop_price_outcome_loop()
    assert outcome_loop.outcome_loop_status()["running"] is False


def test_ingest_prefers_subnet_snapshot(client, intel_env):
    payload = {
        "source": "telegram",
        "content": "Subnet 7 is extremely bullish with strong emission growth!",
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "group_name": "Test",
        "author_id": "u1",
        "author_name": "Alpha",
    }

    class FakePT:
        db = None

        def snapshot(self, message_id):
            raise AssertionError("TAO snapshot should not run when subnet exists")

        def snapshot_subnet(self, message_id, netuid):
            assert netuid == 7
            return 0.42

    with patch("internal.message_intel.engine._load_pipeline") as mock_pipe:
        from message_intel.nlp_engine import NLPAnalyzer

        mock_pipe.return_value = (NLPAnalyzer(), FakePT())
        body = client.post("/api/message-intel/ingest", json=payload).json()

    assert body["status"] == "success"
    assert body.get("price_snapshot", {}).get("subnet_netuid") == 7
    assert body.get("price_snapshot", {}).get("subnet_price") == 0.42


def test_authors_include_hit_rate_fields(client, intel_env):
    from internal.message_intel.store import get_db

    db = get_db()
    msg_id, _ = db.save_message(
        {
            "source": "telegram",
            "author_id": "u1",
            "author_name": "Alpha Trader",
            "author_username": "alpha",
            "content": "Subnet 7 bullish",
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "group_name": "G",
        }
    )
    db.save_analysis(
        msg_id,
        {
            "sentiment": "bullish",
            "sentiment_confidence": 0.9,
            "hype_score": 0.1,
            "substance_score": 0.5,
            "influence_score": 0.6,
            "entities": {"subnets": ["Subnet 7"]},
        },
    )
    db.save_verdict(
        msg_id,
        {
            "verdict": "bullish",
            "conviction": 70,
            "predicted_direction": "up",
            "predicted_magnitude": 0.05,
            "predicted_timeframe": "24h",
            "predicted_confidence": 0.7,
        },
    )
    db.save_price_snapshot(msg_id, 1.0, netuid=7)
    db.save_price_outcome(
        msg_id,
        {
            "price_1h": 1.05,
            "outcome": "mild_pump",
            "pump_pct_max": 5.0,
        },
    )

    authors = client.get("/api/message-intel/authors").json()
    assert authors["status"] == "success"
    assert authors["count"] >= 1
    top = authors["authors"][0]
    assert top["graded"] >= 1
    assert top["hit_rate"] is not None
    assert top["hits"] >= 1


def test_telegram_listener_uses_snapshot_true():
    import inspect
    from internal.message_intel import listener_service

    src = inspect.getsource(listener_service._on_telegram_message)
    assert "snapshot_price=True" in src


def test_subnet_telegram_conviction_api_empty_contract(client):
    listed = client.get("/api/message-intel/subnet-conviction").json()
    detail = client.get("/api/message-intel/subnet-conviction/7").json()
    assert listed["status"] == "success"
    assert listed["empty"] is True
    assert listed["items"] == []
    assert listed["methodology"]["score_range"] == [-100, 100]
    assert detail["status"] == "success"
    assert detail["item"]["state"] == "insufficient_data"
    assert detail["item"]["score"] is None
