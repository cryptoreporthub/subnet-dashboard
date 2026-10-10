"""Hardening: heartbeat refresh, netuid enrichment, telegram pump chip."""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from server import app


@pytest.fixture(autouse=True)
def _listener_service_isolation():
    from internal.message_intel import listener_service
    from internal.message_intel.store import reset_db_cache

    reset_db_cache()
    listener_service._clear_forced_backfill_cache()
    yield
    listener_service._stop_heartbeat_loop()
    listener_service._pending_start_backfill = False
    listener_service._feed_stale_watchdog_strikes = 0
    listener_service._watchdog_strike_generation = -1
    listener_service._watchdog_strike_listener_id = 0
    listener_service._listener = None
    listener_service._clear_forced_backfill_cache()
    listener_service._test_reached_after_recovery = None
    listener_service._test_pause_after_recovery = None
    listener_service._test_reached_before_strike_increment = None
    listener_service._test_pause_before_strike_increment = None
    listener_service._test_reached_before_restart = None
    listener_service._test_pause_before_restart = None
    reset_db_cache()


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


def _alive_thread():
    class _Thr:
        def __init__(self):
            self._alive = True

        def is_alive(self):
            return self._alive

        def join(self, timeout=None):
            self._alive = False

    return _Thr()


def _backfill_ready_listener(**overrides):
    base = {
        "_running": True,
        "_thread": _alive_thread(),
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
    listener_service._listener_generation = 2
    listener_service._clear_forced_backfill_cache()
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
    listener_service._listener_generation = 0
    listener_service._clear_forced_backfill_cache()
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
            self._thread = _alive_thread()
            return True

        def stop(self):
            self.stop_calls += 1
            self._running = False
            if self._thread is not None:
                self._thread.join()

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
        _thread = _alive_thread()
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


def test_feed_stale_watchdog_strikes_when_backfill_raises(monkeypatch):
    listener_service = _watchdog_lifecycle_env(monkeypatch)
    monkeypatch.setenv("TELEGRAM_FEED_STALE_WATCHDOG_STRIKES", "2")

    class _FailListener:
        _running = True
        _thread = _alive_thread()
        group_connected = True
        _monitor_entity = object()
        _loop = object()
        _client = object()

        def trigger_backfill(self, limit=None):
            return False

        def stop(self):
            self._running = False

    fail = _FailListener()
    listener_service._listener = fail
    listener_service._listener_generation = 1
    monkeypatch.setattr(
        listener_service,
        "_feed_stale_fields",
        lambda: {"feed_stale": True, "last_message_age_seconds": 5000.0},
    )
    listener_service._maybe_restart_listener_if_feed_stale()
    assert listener_service._feed_stale_watchdog_strikes == 1
    listener_service._listener = None


def test_restart_aborts_when_retired_thread_still_alive(monkeypatch):
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
            self._thread = _alive_thread()
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
    monkeypatch.setenv("MESSAGE_INTEL_LISTENER_JOIN_SECONDS", "0.01")
    hold = threading.Event()
    zombie = None
    try:
        assert listener_service.start_message_intel_listeners() is True
        zombie = threading.Thread(target=hold.wait, daemon=True)
        zombie.start()
        instances[0]._thread = zombie

        assert listener_service.restart_message_intel_listeners() is False
        assert len(instances) == 1
        assert listener_service._listener is instances[0]
        assert listener_service.start_message_intel_listeners() is False
        assert len(instances) == 1
    finally:
        hold.set()
        if zombie is not None:
            zombie.join(timeout=2)
        listener_service._stop_heartbeat_loop()
        instances[0]._thread = None
        instances[0]._running = False
        listener_service._listener = None
        listener_service._pending_start_backfill = False


def test_forced_backfill_singleflight_two_threads(monkeypatch):
    from internal.message_intel import listener_service

    monkeypatch.setenv("TELEGRAM_FEED_STALE_SECONDS", "60")
    monkeypatch.setenv("TELEGRAM_BACKFILL_INTERVAL_SECONDS", "0")
    listener_service._listener_generation = 1
    listener_service._clear_forced_backfill_cache()
    listener_service._last_backfill_attempt = 0.0
    calls = []

    fake = _backfill_ready_listener()
    gate = threading.Event()

    def trigger_backfill(limit=None):
        calls.append(1)
        gate.wait(timeout=2)
        return True

    fake.trigger_backfill = trigger_backfill
    listener_service._listener = fake
    monkeypatch.setattr(
        listener_service,
        "_feed_stale_fields",
        lambda: {"feed_stale": True, "last_message_age_seconds": 5000.0},
    )

    outcomes: list[str] = []

    def _run():
        outcomes.append(listener_service._attempt_listener_backfill(force=True))

    t1 = threading.Thread(target=_run)
    t2 = threading.Thread(target=_run)
    t1.start()
    t2.start()
    gate.set()
    t1.join(timeout=3)
    t2.join(timeout=3)
    assert len(calls) == 1
    assert outcomes == ["ok", "ok"]
    listener_service._listener = None


def test_forced_backfill_cache_invalidated_on_listener_generation(monkeypatch):
    from internal.message_intel import listener_service

    monkeypatch.setenv("TELEGRAM_FEED_STALE_SECONDS", "60")
    monkeypatch.setenv("TELEGRAM_BACKFILL_INTERVAL_SECONDS", "0")
    listener_service._listener_generation = 1
    listener_service._clear_forced_backfill_cache()
    listener_service._last_backfill_attempt = 0.0
    calls: list[int] = []

    def _make(gen: int):
        fake = _backfill_ready_listener()
        fake.generation = gen

        def trigger_backfill(limit=None):
            calls.append(gen)
            return True

        fake.trigger_backfill = trigger_backfill
        return fake

    listener_service._listener = _make(1)
    monkeypatch.setattr(
        listener_service,
        "_feed_stale_fields",
        lambda: {"feed_stale": True, "last_message_age_seconds": 5000.0},
    )
    assert listener_service._attempt_listener_backfill(force=True) == "ok"
    assert calls == [1]

    listener_service._bump_listener_generation()
    listener_service._listener = _make(2)
    assert listener_service._attempt_listener_backfill(force=True) == "ok"
    assert calls == [1, 2]
    listener_service._listener = None


def test_concurrent_restart_at_most_one_live_owner(monkeypatch):
    instances = []

    class _StubTelegramListener:
        def __init__(self, **kwargs):
            self._running = False
            self._thread = None
            self.group_connected = True
            self._monitor_entity = object()
            self._loop = object()
            self._client = object()
            instances.append(self)

        def start(self):
            self._running = True
            self._thread = _alive_thread()
            return True

        def stop(self):
            self._running = False
            if self._thread is not None:
                self._thread.join()

        def trigger_backfill(self, limit=None):
            return False

    monkeypatch.setattr(
        "message_intel.telegram_listener.TelegramListener",
        _StubTelegramListener,
    )
    listener_service = _watchdog_lifecycle_env(monkeypatch)
    assert listener_service.start_message_intel_listeners() is True

    results: list[bool] = []

    def _restart():
        results.append(listener_service.restart_message_intel_listeners())

    threads = [threading.Thread(target=_restart) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)
    live = [inst for inst in instances if inst._running]
    assert len(live) <= 1
    assert listener_service._listener in instances
    listener_service.stop_message_intel_listeners()


def test_forced_backfill_cache_not_published_after_restart_midflight(monkeypatch):
    from internal.message_intel import listener_service

    monkeypatch.setenv("TELEGRAM_FEED_STALE_SECONDS", "60")
    monkeypatch.setenv("TELEGRAM_BACKFILL_INTERVAL_SECONDS", "0")
    listener_service._clear_forced_backfill_cache()
    listener_service._last_backfill_attempt = 0.0
    calls: list[int] = []
    in_backfill = threading.Event()
    release_backfill = threading.Event()

    def _make_listener(tag: int):
        fake = _backfill_ready_listener()

        def trigger_backfill(limit=None):
            calls.append(tag)
            in_backfill.set()
            release_backfill.wait(timeout=3)
            return True

        fake.trigger_backfill = trigger_backfill
        return fake

    listener_service._listener = _make_listener(1)
    listener_service._listener_generation = 1
    monkeypatch.setattr(
        listener_service,
        "_feed_stale_fields",
        lambda: {"feed_stale": True, "last_message_age_seconds": 5000.0},
    )

    outcome_holder: list[str] = []

    def _backfill():
        outcome_holder.append(listener_service._attempt_listener_backfill(force=True))

    t_backfill = threading.Thread(target=_backfill)
    t_backfill.start()
    assert in_backfill.wait(timeout=3)

    listener_service._bump_listener_generation()
    listener_service._listener = _make_listener(2)

    release_backfill.set()
    t_backfill.join(timeout=3)
    assert outcome_holder == ["not_ready"]

    listener_service._attempt_listener_backfill(force=True)
    assert calls == [1, 2]
    listener_service._listener = None


def test_watchdog_ignores_stale_failed_outcome_after_restart_midflight(monkeypatch):
    from internal.message_intel import listener_service

    monkeypatch.setenv("TELEGRAM_FEED_STALE_SECONDS", "60")
    monkeypatch.setenv("TELEGRAM_FEED_STALE_RESTART_SECONDS", "100")
    monkeypatch.setenv("TELEGRAM_FEED_STALE_WATCHDOG_STRIKES", "1")
    listener_service._clear_forced_backfill_cache()
    listener_service._last_backfill_attempt = 0.0
    calls: list[int] = []
    in_backfill = threading.Event()
    release_backfill = threading.Event()

    def _make_listener(tag: int):
        fake = _backfill_ready_listener()

        def trigger_backfill(limit=None):
            calls.append(tag)
            if tag == 100:
                in_backfill.set()
                release_backfill.wait(timeout=3)
                return False
            return True

        fake.trigger_backfill = trigger_backfill
        fake.stop = lambda: setattr(fake, "_running", False)
        return fake

    listener_service._listener = _make_listener(100)
    listener_service._listener_generation = 100
    listener_service._sync_watchdog_strikes_to_listener_owner()
    monkeypatch.setattr(
        listener_service,
        "_feed_stale_fields",
        lambda: {"feed_stale": True, "last_message_age_seconds": 5000.0},
    )

    def _stale_backfill():
        listener_service._attempt_listener_backfill(force=True)

    t_backfill = threading.Thread(target=_stale_backfill)
    t_backfill.start()
    assert in_backfill.wait(timeout=3)

    listener_service._bump_listener_generation()
    listener_service._listener = _make_listener(101)

    release_backfill.set()
    t_backfill.join(timeout=3)

    listener_service._maybe_restart_listener_if_feed_stale()
    assert listener_service._feed_stale_watchdog_strikes == 0
    assert 101 in calls
    listener_service._listener = None


def _stale_watchdog_env(monkeypatch, listener_service, *, strikes: str = "1"):
    monkeypatch.setenv("TELEGRAM_FEED_STALE_SECONDS", "60")
    monkeypatch.setenv("TELEGRAM_FEED_STALE_RESTART_SECONDS", "100")
    monkeypatch.setenv("TELEGRAM_FEED_STALE_WATCHDOG_STRIKES", strikes)
    listener_service._clear_forced_backfill_cache()
    listener_service._last_backfill_attempt = 0.0
    listener_service._sync_watchdog_strikes_to_listener_owner()
    monkeypatch.setattr(
        listener_service,
        "_feed_stale_fields",
        lambda: {"feed_stale": True, "last_message_age_seconds": 5000.0},
    )


def test_watchdog_fenced_after_failed_recovery_concurrent_restart(monkeypatch):
    from internal.message_intel import listener_service

    instances = []

    class _Stub:
        def __init__(self, tag: int):
            self.tag = tag
            self._running = True
            self._thread = _alive_thread()
            self.group_connected = True
            self._monitor_entity = object()
            self._loop = object()
            self._client = object()
            instances.append(self)

        def trigger_backfill(self, limit=None):
            return False

        def stop(self):
            self._running = False
            if self._thread is not None:
                self._thread.join()

    old = _Stub(1)
    new = _Stub(2)
    listener_service._listener = old
    listener_service._listener_generation = 10
    _stale_watchdog_env(monkeypatch, listener_service, strikes="1")

    reached = threading.Event()
    release = threading.Event()
    done = threading.Event()
    listener_service._test_reached_after_recovery = reached
    listener_service._test_pause_after_recovery = release

    def _watchdog():
        listener_service._maybe_restart_listener_if_feed_stale()
        done.set()

    t = threading.Thread(target=_watchdog)
    t.start()
    assert reached.wait(timeout=3)
    listener_service._bump_listener_generation()
    listener_service._listener = new
    release.set()
    assert done.wait(timeout=3)
    t.join(timeout=3)
    assert listener_service._listener is new
    assert new._running
    listener_service._listener = None
    listener_service._test_pause_after_recovery = None


def test_watchdog_two_strike_restart_fenced_same_invocation(monkeypatch):
    from internal.message_intel import listener_service

    instances = []

    class _Stub:
        def __init__(self, tag: int):
            self.tag = tag
            self._running = True
            self._thread = _alive_thread()
            self.group_connected = True
            self._monitor_entity = object()
            self._loop = object()
            self._client = object()
            instances.append(self)

        def trigger_backfill(self, limit=None):
            return False

        def stop(self):
            self._running = False
            if self._thread is not None:
                self._thread.join()

    old = _Stub(1)
    new = _Stub(2)
    listener_service._listener = old
    listener_service._listener_generation = 20
    _stale_watchdog_env(monkeypatch, listener_service, strikes="2")
    listener_service._feed_stale_watchdog_strikes = 1
    listener_service._watchdog_strike_generation = 20
    listener_service._watchdog_strike_listener_id = id(old)

    reached = threading.Event()
    release = threading.Event()
    done = threading.Event()
    listener_service._test_reached_before_restart = reached
    listener_service._test_pause_before_restart = release

    def _watchdog():
        listener_service._maybe_restart_listener_if_feed_stale()
        done.set()

    t = threading.Thread(target=_watchdog)
    t.start()
    assert reached.wait(timeout=3)
    listener_service._bump_listener_generation()
    listener_service._listener = new
    release.set()
    assert done.wait(timeout=3)
    t.join(timeout=3)
    assert listener_service._listener is new
    assert new._running
    listener_service._listener = None
    listener_service._test_pause_before_restart = None


def test_watchdog_strike_increment_fenced_before_lifecycle_race(monkeypatch):
    """Stale recovery must not poison strikes after concurrent owner swap."""
    from internal.message_intel import listener_service

    instances = []

    class _Stub:
        def __init__(self, tag: int):
            self.tag = tag
            self._running = True
            self._thread = _alive_thread()
            self.group_connected = True
            self._monitor_entity = object()
            self._loop = object()
            self._client = object()
            instances.append(self)

        def trigger_backfill(self, limit=None):
            return False

        def stop(self):
            self._running = False
            if self._thread is not None:
                self._thread.join()

    old = _Stub(1)
    new = _Stub(2)
    listener_service._listener = old
    listener_service._listener_generation = 30
    _stale_watchdog_env(monkeypatch, listener_service, strikes="2")

    reached = threading.Event()
    release = threading.Event()
    done = threading.Event()
    listener_service._test_reached_before_strike_increment = reached
    listener_service._test_pause_before_strike_increment = release

    def _watchdog():
        listener_service._maybe_restart_listener_if_feed_stale()
        done.set()

    t = threading.Thread(target=_watchdog)
    t.start()
    assert reached.wait(timeout=3)
    listener_service._bump_listener_generation()
    listener_service._listener = new
    release.set()
    assert done.wait(timeout=3)
    t.join(timeout=3)

    assert listener_service._listener is new
    assert listener_service._feed_stale_watchdog_strikes == 0
    assert new._running

    restarts: list[int] = []

    def _counting_restart(expected_owner=None):
        restarts.append(id(expected_owner) if expected_owner is not None else 0)
        return False

    monkeypatch.setattr(listener_service, "restart_message_intel_listeners", _counting_restart)

    listener_service._maybe_restart_listener_if_feed_stale()
    assert listener_service._feed_stale_watchdog_strikes == 1
    assert restarts == []

    listener_service._maybe_restart_listener_if_feed_stale()
    assert listener_service._feed_stale_watchdog_strikes == 0
    assert len(restarts) == 1
    assert restarts[0] == id(listener_service._listener)

    listener_service._listener = None
    listener_service._test_pause_before_strike_increment = None

