"""Phase B — web/worker split boot gating."""

from unittest.mock import MagicMock, patch

import pytest

from internal.council import score_snapshots as snaps


@pytest.fixture
def _reset_score_snapshot_scheduler():
    from internal.job_scheduler import cancel_job
    from internal.store.soul_map_io import _cache as soul_map_cache

    snaps.stop_score_snapshot_scheduler()
    with snaps._lock:
        snaps._TICK_ACTIVE = False
        snaps._write_future = None
    soul_map_cache.clear()
    cancel_job(snaps.JOB_ID)
    yield
    snaps.stop_score_snapshot_scheduler()
    soul_map_cache.clear()
    cancel_job(snaps.JOB_ID)


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


def test_worker_essential_starts_pump_snapshot_but_skips_heavy_jobs(
    monkeypatch, tmp_path, _reset_score_snapshot_scheduler
):
    monkeypatch.setenv("RUN_MODE", "worker")
    monkeypatch.setenv("WORKER_HEAVY", "essential")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DATA_DIR_IS_VOLUME", "on")
    monkeypatch.setenv("SCORE_SNAPSHOT_BOOT_IMMEDIATE", "off")
    scheduled = []
    captured = []

    def _defer(name, fn, delay=0):
        scheduled.append(name)
        captured.append((name, fn))

    monkeypatch.setattr("internal.background_boot.defer_boot", _defer)
    monkeypatch.setattr("internal.freshness.start_background_sync", MagicMock())
    for name in (
        "_start_pump_ladder",
        "_start_resolver",
        "_start_whale_warm_scheduler",
        "_start_pick_schedulers",
        "_maybe_start_message_intel",
        "_maybe_start_summary_bot",
        "_warm_judges_cache",
        "_start_pick_audit_scheduler",
        "_start_outcome_snapshot_scheduler",
        "_start_calibration_snapshot_scheduler",
        "_start_dev_radar_github_scheduler",
    ):
        monkeypatch.setattr(f"internal.background_boot.{name}", MagicMock())
    scheduled_jobs: list = []
    monkeypatch.setattr(snaps, "schedule_in_seconds", lambda job_id, fn, sec: scheduled_jobs.append((job_id, fn)))

    from internal.background_boot import start_background_workers

    start_sync = MagicMock()
    bootstrap = MagicMock()
    monkeypatch.setattr("internal.live_subnets.registry_ready", lambda: True)
    monkeypatch.setattr("internal.live_subnets.bootstrap_live_subnets_cache", bootstrap)
    monkeypatch.setattr("internal.live_subnets.start_live_subnets_sync", start_sync)

    start_background_workers()
    assert "live-subnets-boot" in scheduled
    assert "tmp-reaper-hourly" in scheduled
    assert "pump-desk-snapshot" in scheduled
    boot_fn = next(fn for name, fn in captured if name == "live-subnets-boot")
    boot_fn()
    bootstrap.assert_called_once()
    start_sync.assert_called_once()
    score_boot = next(fn for name, fn in captured if name == "score-snapshots")
    score_boot()
    assert [job_id for job_id, _ in scheduled_jobs] == [snaps.JOB_ID]
    scheduler = snaps._scheduler
    assert scheduler is not None
    assert scheduler.state()["running"] is True
    for name in (
        "_warm_judges_cache",
        "_start_pick_audit_scheduler",
        "_start_outcome_snapshot_scheduler",
        "_start_calibration_snapshot_scheduler",
        "_start_dev_radar_github_scheduler",
    ):
        getattr(__import__("internal.background_boot", fromlist=[name]), name).assert_not_called()


def test_start_background_workers_heavy_bootstraps_live_subnets(monkeypatch):
    monkeypatch.setenv("RUN_MODE", "worker")
    monkeypatch.setenv("WORKER_HEAVY", "full")
    bootstrap = MagicMock()
    start_sync = MagicMock()
    scheduled = {}

    def _defer(name, fn, delay=0):
        scheduled[name] = fn

    monkeypatch.setattr("internal.live_subnets.bootstrap_live_subnets_cache", bootstrap)
    monkeypatch.setattr("internal.live_subnets.start_live_subnets_sync", start_sync)
    monkeypatch.setattr("internal.freshness.start_background_sync", MagicMock())
    monkeypatch.setattr("internal.background_boot._start_pump_ladder", MagicMock())
    monkeypatch.setattr("internal.background_boot._start_resolver", MagicMock())
    monkeypatch.setattr("internal.background_boot._start_whale_warm_scheduler", MagicMock())
    monkeypatch.setattr("internal.background_boot.defer_boot", _defer)
    monkeypatch.setattr("internal.live_subnets.registry_ready", lambda: True)

    from internal.background_boot import start_background_workers

    start_background_workers(heavy=True)
    assert "live-subnets-boot" in scheduled
    scheduled["live-subnets-boot"]()
    bootstrap.assert_called_once()
    start_sync.assert_called_once()


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


def test_resolver_scheduler_boots_immediately_on_worker(monkeypatch):
    scheduled = {}
    monkeypatch.setenv("RUN_MODE", "worker")

    def _defer(name, fn, delay=0):
        scheduled[name] = delay

    monkeypatch.setattr("internal.background_boot.defer_boot", _defer)
    from internal.background_boot import _start_resolver

    _start_resolver()

    assert scheduled["prediction-resolver"] == 0


def test_resolver_scheduler_stays_deferred_on_web(monkeypatch):
    scheduled = {}
    monkeypatch.setenv("RUN_MODE", "web")
    monkeypatch.setattr("internal.background_boot.BOOT_DEFER_SECONDS", 90)

    def _defer(name, fn, delay=0):
        scheduled[name] = delay

    monkeypatch.setattr("internal.background_boot.defer_boot", _defer)
    from internal.background_boot import _start_resolver

    _start_resolver()

    assert scheduled["prediction-resolver"] >= 100


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


def test_message_intel_listener_starts_immediately_on_worker(monkeypatch):
    monkeypatch.setenv("RUN_MODE", "worker")
    monkeypatch.setenv("MESSAGE_INTEL_LISTENER", "auto")
    monkeypatch.setenv("BOOT_DEFER_SECONDS", "90")
    scheduled = {}

    monkeypatch.setattr(
        "internal.background_boot.defer_boot",
        lambda name, fn, delay=0: scheduled.__setitem__(name, delay),
    )

    from internal.background_boot import _maybe_start_message_intel

    _maybe_start_message_intel()

    assert scheduled["message-intel-listeners"] == 0


def test_message_intel_listener_stays_deferred_on_web(monkeypatch):
    monkeypatch.setenv("RUN_MODE", "web")
    monkeypatch.setenv("MESSAGE_INTEL_LISTENER", "auto")
    monkeypatch.setattr("internal.background_boot.BOOT_DEFER_SECONDS", 90)
    scheduled = {}

    monkeypatch.setattr(
        "internal.background_boot.defer_boot",
        lambda name, fn, delay=0: scheduled.__setitem__(name, delay),
    )

    from internal.background_boot import _maybe_start_message_intel

    _maybe_start_message_intel()

    assert scheduled["message-intel-listeners"] == 150


def test_message_intel_listener_worker_override_is_preserved(monkeypatch):
    monkeypatch.setenv("RUN_MODE", "worker")
    monkeypatch.setenv("MESSAGE_INTEL_LISTENER", "auto")
    monkeypatch.setenv("MESSAGE_INTEL_LISTENER_DEFER_SECONDS", "12")
    scheduled = {}

    monkeypatch.setattr(
        "internal.background_boot.defer_boot",
        lambda name, fn, delay=0: scheduled.__setitem__(name, delay),
    )

    from internal.background_boot import _maybe_start_message_intel

    _maybe_start_message_intel()

    assert scheduled["message-intel-listeners"] == 12


def test_worker_peer_split_v2_web(monkeypatch):
    from internal.learning.loop_health import _worker_peer

    monkeypatch.setenv("RUN_MODE", "web")
    monkeypatch.setenv("WORKER_SPLIT_V2", "on")
    monkeypatch.setenv("INLINE_WORKER", "0")
    remote = {
        "worker_peer": {
            "alive": True,
            "source": "file",
            "heartbeat": {"ts": "2026-07-28T16:00:00Z"},
        }
    }
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


def test_maybe_start_summary_bot_skips_on_web(monkeypatch):
    monkeypatch.setenv("RUN_MODE", "web")
    monkeypatch.setenv("TELEGRAM_SUMMARY_BOT", "on")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:ABC")
    deferred = []

    monkeypatch.setattr(
        "internal.background_boot.defer_boot",
        lambda name, fn, delay=0: deferred.append((name, delay)),
    )

    from internal.background_boot import _maybe_start_summary_bot

    _maybe_start_summary_bot()
    assert deferred == []


def test_maybe_start_summary_bot_defers_on_worker(monkeypatch):
    monkeypatch.setenv("RUN_MODE", "worker")
    monkeypatch.setenv("TELEGRAM_SUMMARY_BOT", "on")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:ABC")
    deferred = []

    monkeypatch.setattr(
        "internal.background_boot.defer_boot",
        lambda name, fn, delay=0: deferred.append((name, delay)),
    )

    from internal.background_boot import _maybe_start_summary_bot

    _maybe_start_summary_bot()
    assert deferred == [("telegram-summary-bot", 15)]


def test_summary_bot_worker_defer_seconds_env_override(monkeypatch):
    monkeypatch.setenv("RUN_MODE", "worker")
    monkeypatch.setenv("TELEGRAM_SUMMARY_BOT_DEFER_SECONDS", "3")
    from internal.background_boot import _summary_bot_defer_seconds

    assert _summary_bot_defer_seconds() == 3


def test_ops_readiness_worker_mode_field():
    from fastapi.testclient import TestClient

    from server import app

    client = TestClient(app)
    resp = client.get("/api/ops/readiness")
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("worker_mode") in ("web", "worker", "combined", "split", "split_v2")
