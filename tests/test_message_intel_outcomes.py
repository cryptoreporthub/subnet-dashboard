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


def test_price_outcome_records_24h_observation_timestamp_once(intel_env):
    """A first-hour receipt is enriched at 24h instead of duplicating outcomes."""
    from internal.message_intel.store import get_db

    db = get_db()
    message_id, _ = db.save_message(
        {
            "source": "telegram",
            "group_id": "test",
            "message_id": "outcome-timestamp-1",
            "author_id": "u1",
            "author_name": "Alpha",
            "content": "Subnet 7 bullish",
        }
    )
    db.save_price_outcome(message_id, {"price_1h": 1.0, "outcome": "stable"})
    db.save_price_outcome(
        message_id,
        {
            "price_1h": 1.1,
            "price_24h": 1.2,
            "price_24h_recorded_at": "2026-08-01T00:00:00+00:00",
            "outcome": "pump",
        },
    )

    with db._connect() as conn:
        rows = conn.execute(
            """SELECT price_1h, price_24h, price_24h_recorded_at
               FROM price_outcomes WHERE message_id = ?""",
            (message_id,),
        ).fetchall()

    assert len(rows) == 1
    assert rows[0]["price_1h"] == 1.1
    assert rows[0]["price_24h"] == 1.2
    assert rows[0]["price_24h_recorded_at"] == "2026-08-01T00:00:00+00:00"


def test_tracker_enriches_first_hour_outcome_at_24h_once(intel_env, monkeypatch):
    """The normal tracker lifecycle makes a divergence-ready receipt."""
    from internal.message_intel import rollup
    from internal.message_intel.store import get_db
    from message_intel.price_tracker import PriceTracker

    db = get_db()
    snapshot_at = datetime.now(timezone.utc) - timedelta(hours=2)
    message_id, _ = db.save_message(
        {
            "source": "telegram",
            "group_id": "test",
            "message_id": "outcome-lifecycle-1",
            "author_id": "u1",
            "author_name": "Alpha",
            "content": "Subnet 7 bullish",
            "timestamp": snapshot_at.isoformat(),
        }
    )
    db.save_analysis(
        message_id,
        {
            "entities": {"subnets": [7]},
            "sentiment": "bullish",
            "sentiment_confidence": 0.9,
            "hype_score": 0.1,
            "substance_score": 0.8,
            "influence_score": 0.7,
        },
    )
    db.save_verdict(
        message_id,
        {
            "verdict": "bullish",
            "conviction": 80,
            "predicted_direction": "up",
        },
    )
    db.save_price_snapshot(message_id, 1.0, netuid=7)
    with db._connect() as conn:
        conn.execute(
            "UPDATE price_snapshots SET snapshot_timestamp = ? WHERE message_id = ?",
            (snapshot_at.isoformat(), message_id),
        )

    tracker = PriceTracker(db=db)
    monkeypatch.setattr(
        "message_intel.price_tracker.fetch_all_subnet_prices",
        lambda: {7: {"price": 1.1}},
    )
    monkeypatch.setattr(
        "message_intel.price_tracker.fetch_subnet_price",
        lambda _netuid: {"price": 1.1},
    )
    tracker.check_outcomes()

    with db._connect() as conn:
        first = conn.execute(
            "SELECT id, price_24h, price_24h_recorded_at FROM price_outcomes WHERE message_id = ?",
            (message_id,),
        ).fetchone()
    assert first["price_24h"] is None
    assert first["price_24h_recorded_at"] is None
    assert db.get_unresolved_outcomes()[0]["outcome_id"] == first["id"]

    mature_at = datetime.now(timezone.utc) - timedelta(hours=25)
    with db._connect() as conn:
        conn.execute(
            "UPDATE price_snapshots SET snapshot_timestamp = ? WHERE message_id = ?",
            (mature_at.isoformat(), message_id),
        )
    tracker.check_outcomes()

    with db._connect() as conn:
        rows = conn.execute(
            """SELECT id, price_24h, price_24h_recorded_at
               FROM price_outcomes WHERE message_id = ?""",
            (message_id,),
        ).fetchall()
    assert len(rows) == 1
    assert rows[0]["id"] == first["id"]
    assert rows[0]["price_24h"] == 1.1
    assert rows[0]["price_24h_recorded_at"] is not None
    assert db.get_unresolved_outcomes() == []

    story_rows = [row for row in rollup._conviction_rows(db) if row["id"] == message_id]
    assert len(story_rows) == 1
    assert rollup._has_24h_observation(
        story_rows[0],
        mature_at,
    )


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


def test_telegram_divergence_api_empty_contract(client):
    listed = client.get("/api/message-intel/divergence?days=7&limit=3").json()
    detail = client.get("/api/message-intel/divergence/7?days=7").json()
    assert listed["status"] == "success"
    assert listed["empty"] is True
    assert listed["stories"] == []
    assert listed["methodology"]["horizon"] == "24h"
    assert listed["methodology"]["minimum_calls"] == 2
    assert detail["status"] == "success"
    assert detail["story"] is None
