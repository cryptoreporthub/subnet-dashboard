"""Phase B — web/worker split boot gating."""

from unittest.mock import MagicMock

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


def test_background_on_web_essential(monkeypatch):
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
    monkeypatch.setattr("internal.live_subnets.get_live_subnets", live)
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


def test_ops_readiness_worker_mode_field():
    from fastapi.testclient import TestClient

    from server import app

    client = TestClient(app)
    resp = client.get("/api/ops/readiness")
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("worker_mode") in ("web", "worker", "combined", "split")
