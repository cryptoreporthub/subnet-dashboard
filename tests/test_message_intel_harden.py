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


def _backfill_ready_listener(**overrides):
    base = {
        "_running": True,
        "group_connected": True,
        "_monitor_entity": object(),
        "_loop": object(),
        "_client": object(),
    }
    base.update(overrides)

    class _Fake:
        pass

    fake = _Fake()
    for key, val in base.items():
        setattr(fake, key, val)
    return fake


def test_listener_backfill_when_feed_stale(monkeypatch):
    from internal.message_intel import listener_service

    monkeypatch.setenv("TELEGRAM_FEED_STALE_SECONDS", "60")
    monkeypatch.setenv("TELEGRAM_BACKFILL_INTERVAL_SECONDS", "0")
    listener_service._last_backfill_attempt = 0.0
    listener_service._last_backfill_outcome = None
    listener_service._last_backfill_outcome_at = 0.0

    fake = _backfill_ready_listener()
    fake.called = False

    def trigger_backfill(self, limit=None):
        self.called = True
        return True

    fake.trigger_backfill = lambda limit=None: trigger_backfill(fake, limit)
    listener_service._listener = fake
    monkeypatch.setattr(
        listener_service,
        "_feed_stale_fields",
        lambda: {"feed_stale": True, "last_message_age_seconds": 9999.0},
    )
    assert listener_service._maybe_backfill_if_stale()
    assert fake.called
    listener_service._listener = None


def test_listener_start_backfill_deferred_until_ready(monkeypatch):
    from internal.message_intel import listener_service

    monkeypatch.setenv("TELEGRAM_GAP_BACKFILL_SECONDS", "60")
    listener_service._last_backfill_attempt = 0.0
    listener_service._last_backfill_outcome = None
    listener_service._last_backfill_outcome_at = 0.0
    listener_service._pending_start_backfill = True

    fake = _backfill_ready_listener(group_connected=False, _monitor_entity=None)
    fake.called = False
    fake.trigger_backfill = lambda limit=None: setattr(fake, "called", True) or True
    listener_service._listener = fake
    monkeypatch.setattr(
        listener_service,
        "_feed_stale_fields",
        lambda: {"feed_stale": False, "last_message_age_seconds": 120.0},
    )
    listener_service._maybe_backfill_on_listener_start()
    assert not fake.called
    assert listener_service._last_backfill_attempt == 0.0
    assert listener_service._pending_start_backfill

    fake.group_connected = True
    fake._monitor_entity = object()
    listener_service._maybe_backfill_on_listener_start()
    assert fake.called
    assert not listener_service._pending_start_backfill
    listener_service._listener = None


def test_listener_start_backfill_when_gap_old(monkeypatch):
    from internal.message_intel import listener_service

    monkeypatch.setenv("TELEGRAM_GAP_BACKFILL_SECONDS", "60")
    listener_service._last_backfill_attempt = 0.0
    listener_service._last_backfill_outcome = None
    listener_service._last_backfill_outcome_at = 0.0
    listener_service._pending_start_backfill = True

    fake = _backfill_ready_listener()
    fake.called = False
    fake.trigger_backfill = lambda limit=None: setattr(fake, "called", True) or True
    listener_service._listener = fake
    monkeypatch.setattr(
        listener_service,
        "_feed_stale_fields",
        lambda: {"feed_stale": False, "last_message_age_seconds": 120.0},
    )
    listener_service._maybe_backfill_on_listener_start()
    assert fake.called
    listener_service._listener = None


def _watchdog_lifecycle_env(monkeypatch):
    from internal.message_intel import listener_service

    monkeypatch.setenv("MESSAGE_INTEL_LISTENER", "auto")
    monkeypatch.setenv("TELEGRAM_API_ID", "12345")
    monkeypatch.setenv("TELEGRAM_API_HASH", "deadbeef")
    monkeypatch.setenv("TELEGRAM_FEED_STALE_SECONDS", "60")
    monkeypatch.setenv("TELEGRAM_FEED_STALE_RESTART_SECONDS", "100")
    monkeypatch.setenv("TELEGRAM_BACKFILL_INTERVAL_SECONDS", "0")
    monkeypatch.setattr(
        "internal.message_intel.session.telegram_session_arg",
        lambda: "fake-session",
    )
    monkeypatch.setattr(
        "internal.message_intel.session.has_telegram_session",
        lambda: True,
    )
    listener_service._feed_stale_watchdog_strikes = 0
    listener_service._last_backfill_attempt = 0.0
    listener_service._last_backfill_outcome = None
    listener_service._last_backfill_outcome_at = 0.0
    listener_service._pending_start_backfill = False
    listener_service._listener = None
    listener_service._heartbeat_stop = None
    return listener_service


def test_feed_stale_watchdog_restart_real_lifecycle(monkeypatch):
    instances = []

    class _StubTelegramListener:
        def __init__(self, **kwargs):
            self._running = False
            self._thread = None
            self.group_connected = True
            self._monitor_entity = object()
            self._loop = object()
            self._client = object()
            self.stop_calls = 0
            instances.append(self)

        def start(self):
            self._running = True
            return True

        def stop(self):
            self.stop_calls += 1
            self._running = False

        def trigger_backfill(self, limit=None):
            return False

    monkeypatch.setattr(
        "message_intel.telegram_listener.TelegramListener",
        _StubTelegramListener,
    )
    listener_service = _watchdog_lifecycle_env(monkeypatch)
    monkeypatch.setattr(
        listener_service,
        "_feed_stale_fields",
        lambda: {"feed_stale": True, "last_message_age_seconds": 5000.0},
    )

    assert listener_service.start_message_intel_listeners() is True
    first = instances[0]
    assert first._running

    listener_service._maybe_restart_listener_if_feed_stale()
    assert first.stop_calls == 0
    listener_service._maybe_restart_listener_if_feed_stale()
    assert first.stop_calls >= 1
    assert len(instances) >= 2
    assert instances[-1] is not first
    assert listener_service._listener is instances[-1]
    listener_service.stop_message_intel_listeners()


def test_feed_stale_watchdog_no_strike_on_quiet_group_empty_scan(monkeypatch):
    listener_service = _watchdog_lifecycle_env(monkeypatch)

    class _QuietListener:
        _running = True
        group_connected = True
        _monitor_entity = object()
        _loop = object()
        _client = object()

        def trigger_backfill(self, limit=None):
            return True

        def stop(self):
            self._running = False

    quiet = _QuietListener()
    listener_service._listener = quiet
    monkeypatch.setattr(
        listener_service,
        "_feed_stale_fields",
        lambda: {"feed_stale": True, "last_message_age_seconds": 5000.0},
    )

    for _ in range(4):
        listener_service._maybe_restart_listener_if_feed_stale()
    assert listener_service._feed_stale_watchdog_strikes == 0
    assert quiet._running
    listener_service._listener = None

