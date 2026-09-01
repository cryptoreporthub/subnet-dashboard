"""Pump desk snapshot worker — read-only ops probe."""

from __future__ import annotations

import internal.pump.desk_snapshot as snap
import internal.pump.desk_snapshot_scheduler as sched


def test_evaluate_alerts_ok():
    pump = {"status": "ok", "alerts": []}
    health = {"status": "ok", "worker_peer": {"alive": True}}
    level, reasons = snap._evaluate_alerts(pump, health)
    assert level == "ok"
    assert reasons == []


def test_evaluate_alerts_warn_on_building_badge():
    pump = {
        "status": "ok",
        "alerts": [{"netuid": 12, "name": "SN12", "badge": "BUILDING", "move": "+8%"}],
    }
    health = {"status": "ok", "worker_peer": {"alive": True}}
    level, reasons = snap._evaluate_alerts(pump, health)
    assert level == "warn"
    assert any("BUILDING" in r for r in reasons)


def test_evaluate_alerts_alert_on_stalled_loop():
    pump = {"status": "ok", "alerts": []}
    health = {"status": "stalled", "worker_peer": {"alive": True}}
    level, reasons = snap._evaluate_alerts(pump, health)
    assert level == "alert"
    assert any("learning_loop" in r for r in reasons)


def test_exit_code_for_level():
    assert snap.exit_code_for_level("ok") == 0
    assert snap.exit_code_for_level("warn") == 0
    assert snap.exit_code_for_level("alert") == 2


def test_build_snapshot_uses_collectors(monkeypatch):
    monkeypatch.setattr(
        snap,
        "_collect_pump_desk",
        lambda: {"status": "ok", "count": 3, "early_count": 1, "confirmed_count": 2, "alerts": []},
    )
    monkeypatch.setattr(
        snap,
        "_collect_learning_health",
        lambda: {
            "status": "ok",
            "pending": 0,
            "worker_peer": {"alive": True},
            "daily_pick": {"action": "long", "netuid": 40},
        },
    )
    payload = snap.build_pump_desk_snapshot()
    assert payload["alert_level"] == "ok"
    assert payload["pump_desk"]["count"] == 3
    assert payload["daily_pick"]["netuid"] == 40


def test_save_snapshot_writes_latest(tmp_path, monkeypatch):
    monkeypatch.setenv("PUMP_DESK_SNAPSHOT_DIR", str(tmp_path))
    payload = {"status": "ok", "alert_level": "ok"}
    path = snap.save_snapshot(payload)
    assert path.endswith(".json")
    latest = tmp_path / "latest.json"
    assert latest.is_file()


def test_scheduler_disabled(monkeypatch):
    monkeypatch.setenv("PUMP_DESK_SNAPSHOT_ENABLED", "off")
    out = sched.start_pump_desk_snapshot_scheduler()
    assert out["started"] is False
    assert out["reason"] == "disabled"


def test_scheduler_run_once(monkeypatch):
    monkeypatch.setattr(
        "internal.pump.desk_snapshot.run_snapshot",
        lambda save=True: {"alert_level": "ok", "path": "/tmp/x.json"},
    )
    s = sched.PumpDeskSnapshotScheduler(interval_minutes=15)
    result = s.run_once()
    assert result["ok"] is True
    assert result["alert_level"] == "ok"


def test_scheduler_timeout_is_recorded(monkeypatch):
    import time

    monkeypatch.setattr(sched, "SNAPSHOT_TIMEOUT_SECONDS", 1)
    monkeypatch.setattr(
        "internal.pump.desk_snapshot.run_snapshot",
        lambda save=True: (time.sleep(1.1) or {"alert_level": "ok"}),
    )
    s = sched.PumpDeskSnapshotScheduler(interval_minutes=15)

    result = s.run_once()

    assert result["ok"] is False
    assert result["error"] == "cycle_timeout_1s"
    assert s.liveness.snapshot()["status"] == "failing"


def test_pump_desk_snapshot_tracker_is_liveness_compliant(monkeypatch, tmp_path):
    from tests.liveness_conformance import assert_liveness_compliant

    soul = tmp_path / "soul_map.json"
    soul.write_text("{}")
    monkeypatch.setenv("SOUL_MAP_PATH", str(soul))
    monkeypatch.setattr("internal.council.weights.SOUL_MAP_PATH", str(soul))

    def factory():
        return sched.PumpDeskSnapshotScheduler().liveness

    assert_liveness_compliant(factory)
