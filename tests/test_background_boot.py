"""Phase B — web/worker split boot gating."""

from unittest.mock import MagicMock, patch

import pytest


def test_background_on_web_off_skips_resolver(monkeypatch):
    monkeypatch.setenv("BACKGROUND_ON_WEB", "off")
    monkeypatch.setenv("RUN_MODE", "web")

    import internal.background_boot as boot
    import internal.run_mode as run_mode

    monkeypatch.setattr(run_mode, "get_run_mode", lambda: "web")
    monkeypatch.setattr(run_mode, "background_on_web", lambda: False)

    started = MagicMock()
    monkeypatch.setattr(
        "internal.council.resolver_scheduler.start_prediction_resolver_scheduler",
        started,
    )

    from internal.run_mode import background_on_web

    assert background_on_web() is False
    # Lifespan gate: when off, start_background_workers is not called from server.
    # Direct call still starts (worker path) — verify gate logic only here.


def test_background_on_web_on_by_default(monkeypatch):
    monkeypatch.delenv("BACKGROUND_ON_WEB", raising=False)
    monkeypatch.setenv("RUN_MODE", "web")

    from internal.run_mode import background_on_web

    assert background_on_web() is True


def test_worker_mode_label(monkeypatch):
    from internal.run_mode import worker_mode_label

    monkeypatch.setenv("RUN_MODE", "worker")
    monkeypatch.setenv("BACKGROUND_ON_WEB", "off")
    assert worker_mode_label() == "worker"

    monkeypatch.setenv("RUN_MODE", "web")
    monkeypatch.setenv("BACKGROUND_ON_WEB", "off")
    assert worker_mode_label() == "web"

    monkeypatch.setenv("RUN_MODE", "web")
    monkeypatch.setenv("BACKGROUND_ON_WEB", "on")
    assert worker_mode_label() == "combined"


def test_worker_heavy_feeds_full_only(monkeypatch):
    from internal.run_mode import worker_heavy_feeds_enabled

    monkeypatch.setenv("WORKER_HEAVY", "essential")
    assert worker_heavy_feeds_enabled() is False
    monkeypatch.setenv("WORKER_HEAVY", "full")
    assert worker_heavy_feeds_enabled() is True
    monkeypatch.setenv("BACKGROUND_ON_WEB", "essential")
    monkeypatch.setenv("RUN_MODE", "web")

    from internal.run_mode import background_heavy_on_web, background_on_web

    assert background_on_web() is True
    assert background_heavy_on_web() is False


def test_background_heavy_on_full(monkeypatch):
    monkeypatch.setenv("BACKGROUND_ON_WEB", "on")
    monkeypatch.setenv("RUN_MODE", "web")

    from internal.run_mode import background_heavy_on_web, background_on_web

    assert background_on_web() is True
    assert background_heavy_on_web() is True


def test_start_background_workers_essential_skips_live_subnets(monkeypatch):
    live = MagicMock()
    bootstrap = MagicMock()
    monkeypatch.setattr("internal.live_subnets.get_live_subnets", live)
    monkeypatch.setattr("internal.live_subnets.bootstrap_live_subnets_cache", bootstrap)
    monkeypatch.setattr("internal.freshness.start_background_sync", MagicMock())
    monkeypatch.setattr(
        "internal.council.resolver_scheduler.start_prediction_resolver_scheduler",
        MagicMock(),
    )
    monkeypatch.setattr("internal.message_intel.listener_service.start_message_intel_listeners", MagicMock())
    monkeypatch.setattr("internal.background_boot._start_pump_ladder", MagicMock())
    monkeypatch.setattr("internal.background_boot._start_resolver", MagicMock())
    monkeypatch.setattr("internal.background_boot._start_whale_warm_scheduler", MagicMock())

    from internal.background_boot import start_background_workers

    start_background_workers(heavy=False)
    live.assert_not_called()
    bootstrap.assert_not_called()


def test_start_background_workers_heavy_bootstraps_live_subnets(monkeypatch):
    live = MagicMock()
    bootstrap = MagicMock(return_value=True)
    monkeypatch.setattr("internal.live_subnets.get_live_subnets", live)
    monkeypatch.setattr("internal.live_subnets.bootstrap_live_subnets_cache", bootstrap)
    monkeypatch.setattr("internal.freshness.start_background_sync", MagicMock())
    monkeypatch.setattr("internal.background_boot._start_pump_ladder", MagicMock())
    monkeypatch.setattr("internal.background_boot._start_resolver", MagicMock())
    monkeypatch.setattr("internal.background_boot._start_whale_warm_scheduler", MagicMock())
    monkeypatch.setattr("internal.background_boot.defer_boot", MagicMock())

    from internal.background_boot import start_background_workers

    start_background_workers(heavy=True)
    bootstrap.assert_called_once()
    live.assert_not_called()  # defer_boot mocked; bootstrap is sync path


def test_start_background_workers_starts_resolver(monkeypatch):
    resolver = MagicMock()
    pump = MagicMock()
    whale = MagicMock()
    monkeypatch.setattr("internal.background_boot._start_resolver", resolver)
    monkeypatch.setattr("internal.background_boot._start_pump_ladder", pump)
    monkeypatch.setattr("internal.background_boot._start_whale_warm_scheduler", whale)
    monkeypatch.setattr("internal.freshness.start_background_sync", MagicMock())
    monkeypatch.setattr("internal.message_intel.listener_service.start_message_intel_listeners", MagicMock())

    from internal.background_boot import start_background_workers

    start_background_workers()
    resolver.assert_called_once()
    pump.assert_called_once()
    whale.assert_called_once()


def test_worker_mode_label_split(monkeypatch):
    from internal.run_mode import worker_mode_label

    monkeypatch.setenv("RUN_MODE", "web")
    monkeypatch.setenv("BACKGROUND_ON_WEB", "off")
    monkeypatch.setenv("INLINE_WORKER", "1")
    assert worker_mode_label() == "split"

    monkeypatch.setenv("WORKER_SPLIT_V2", "on")
    monkeypatch.setenv("INLINE_WORKER", "0")
    assert worker_mode_label() == "split_v2"


def test_pump_inline_defer_seconds_default(monkeypatch):
    monkeypatch.delenv("PUMP_LADDER_INLINE_DEFER_SECONDS", raising=False)
    from internal.background_boot import _pump_inline_defer_seconds

    assert _pump_inline_defer_seconds() == 300


def test_pump_inline_defer_seconds_env(monkeypatch):
    monkeypatch.setenv("PUMP_LADDER_INLINE_DEFER_SECONDS", "420")
    from internal.background_boot import _pump_inline_defer_seconds

    assert _pump_inline_defer_seconds() == 420


def test_pump_inline_scheduler_disabled_by_default(monkeypatch):
    monkeypatch.delenv("PUMP_LADDER_INLINE_SCHEDULER", raising=False)
    from internal.background_boot import _pump_inline_scheduler_enabled

    assert _pump_inline_scheduler_enabled() is False


def test_pump_inline_scheduler_env_on(monkeypatch):
    monkeypatch.setenv("PUMP_LADDER_INLINE_SCHEDULER", "on")
    from internal.background_boot import _pump_inline_scheduler_enabled

    assert _pump_inline_scheduler_enabled() is True


def test_outcomes_start_when_listener_off(monkeypatch):
    monkeypatch.setenv("MESSAGE_INTEL_LISTENER", "off")
    monkeypatch.setenv("MESSAGE_INTEL_OUTCOMES", "on")
    scheduled = {}

    def _defer(name, fn, delay=0):
        scheduled[name] = delay

    monkeypatch.setattr("internal.background_boot.defer_boot", _defer)
    from internal.background_boot import _maybe_start_message_intel

    _maybe_start_message_intel()
    assert "message-intel-outcomes" in scheduled
    assert "message-intel-listeners" not in scheduled


def test_worker_peer_split_v2_web(monkeypatch):
    from internal.learning.loop_health import _worker_peer

    monkeypatch.setenv("RUN_MODE", "web")
    monkeypatch.setenv("WORKER_SPLIT_V2", "on")
    monkeypatch.setenv("INLINE_WORKER", "0")
    remote = {"worker_peer": {"alive": True, "heartbeat": {"ts": "2026-07-28T16:00:00Z"}}}
    with patch("internal.worker_proxy.fetch_worker_json_sync", return_value=remote):
        peer = _worker_peer()
    assert peer["peer"] == "dedicated_worker"
    assert peer["expected"] is True
    assert peer["alive"] is True
    assert peer.get("source") == "http"


def test_worker_peer_split_v2_worker(monkeypatch, tmp_path):
    from internal.learning.loop_health import _worker_peer

    monkeypatch.setenv("RUN_MODE", "worker")
    monkeypatch.setenv("WORKER_SPLIT_V2", "on")
    monkeypatch.setenv("WORKER_HEARTBEAT_PATH", str(tmp_path / ".worker_heartbeat"))
    from internal.worker_heartbeat import touch_heartbeat

    touch_heartbeat()
    peer = _worker_peer()
    assert peer["peer"] == "dedicated_worker"
    assert peer["alive"] is True


def test_ops_readiness_worker_mode_field():
    from fastapi.testclient import TestClient

    from server import app

    client = TestClient(app)
    resp = client.get("/api/ops/readiness")
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("worker_mode") in ("web", "worker", "combined", "split", "split_v2")
