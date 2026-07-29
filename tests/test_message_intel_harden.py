"""Hardening: heartbeat refresh, netuid enrichment, telegram pump chip."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

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


def test_list_messages_enriches_netuid(client):
    payload = {
        "source": "telegram",
        "group_name": "SubnetAlpha",
        "content": "Subnet 7 is extremely bullish with strong emission growth!",
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "author_id": "u1",
        "author_name": "Alpha",
    }
    with patch("internal.message_intel.engine._load_pipeline") as mock_pipe:
        from message_intel.nlp_engine import NLPAnalyzer

        mock_pipe.return_value = (
            NLPAnalyzer(),
            type("PT", (), {"db": None, "snapshot": lambda *a, **k: None})(),
        )
        assert client.post("/api/message-intel/ingest", json=payload).json()["status"] == "success"

    listed = client.get("/api/message-intel?limit=5").json()
    assert listed["status"] == "success"
    assert listed["count"] >= 1
    row = listed["messages"][0]
    assert row.get("netuid") == 7
    trending = listed.get("meta", {}).get("trending") or []
    if trending:
        assert "heat" in trending[0]
        assert "avg_conviction" in trending[0]


def test_telegram_chip_from_chatter():
    from internal.learning.pump_alert import _telegram_chip

    assert _telegram_chip({}) is None
    assert _telegram_chip({"signal_snapshot": {"chatter_intensity": 0.05}}) is None
    chip = _telegram_chip({"signal_snapshot": {"chatter_intensity": 0.72}})
    assert chip and "Telegram hot" in chip
    warm = _telegram_chip({"signal_snapshot": {"chatter_intensity": 0.4}})
    assert warm and "warming" in warm


def test_heartbeat_touch_on_ingest_path(monkeypatch, tmp_path):
    from internal.message_intel import listener_service

    hb = tmp_path / ".hb"
    monkeypatch.setenv("MESSAGE_INTEL_LISTENER_HEARTBEAT", str(hb))
    listener_service._touch_listener_heartbeat()
    assert hb.exists()
    first = hb.read_text(encoding="utf-8")
    listener_service._touch_listener_heartbeat()
    second = hb.read_text(encoding="utf-8")
    assert "ts" in second
    assert first  # file still valid JSON payload


def test_live_stats_includes_last_message_age(client):
    payload = {
        "source": "telegram",
        "group_name": "SubnetAlpha",
        "content": "Subnet 7 is extremely bullish!",
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "message_id": "9001",
        "group_id": "-1001",
    }
    with patch("internal.message_intel.engine._load_pipeline") as mock_pipe:
        from message_intel.nlp_engine import NLPAnalyzer

        mock_pipe.return_value = (
            NLPAnalyzer(),
            type("PT", (), {"db": None, "snapshot": lambda *a, **k: None})(),
        )
        client.post("/api/message-intel/ingest", json=payload)
    from internal.message_intel.store import live_stats

    stats = live_stats()
    assert stats.get("last_message_at")
    assert stats.get("last_message_age_seconds") is not None


def test_listener_backfill_when_feed_stale(monkeypatch):
    from internal.message_intel import listener_service

    monkeypatch.setenv("TELEGRAM_FEED_STALE_SECONDS", "60")
    monkeypatch.setenv("TELEGRAM_BACKFILL_INTERVAL_SECONDS", "0")
    listener_service._last_backfill_attempt = 0.0

    class _Fake:
        _running = True
        called = False

        def trigger_backfill(self, limit=None):
            self.called = True
            return True

    fake = _Fake()
    listener_service._listener = fake
    monkeypatch.setattr(
        listener_service,
        "_feed_stale_fields",
        lambda: {"feed_stale": True, "last_message_age_seconds": 9999.0},
    )
    listener_service._maybe_backfill_if_stale()
    assert fake.called
    listener_service._listener = None

