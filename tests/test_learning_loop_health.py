"""Phase 0 — learning loop health + ledger contract guard."""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from internal.learning import loop_health
from internal.learning import routes
from internal.learning.loop_health import build_learning_loop_health
from server import app


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _seed_resolver_liveness(monkeypatch, *, fresh: bool = True, stale_seconds: float = 0.0):
    """Install a prediction_resolver tracker for loop_health registry lookup."""
    from internal.liveness import LivenessTracker

    tracker = LivenessTracker(name="prediction_resolver", interval_seconds=900, persist=False)
    if fresh:
        tracker.record_success(evidence={"resolved_now": 0})
        if stale_seconds > 0:
            tracker._last_success_epoch = time.time() - stale_seconds
    monkeypatch.setattr(
        "internal.liveness.get_tracker",
        lambda name: tracker if name == "prediction_resolver" else None,
    )
    return tracker


def test_api_learning_health_shape():
    client = TestClient(app)
    res = client.get("/api/learning/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] in ("ok", "degraded", "stalled")
    for key in (
        "pending",
        "last_resolver_tick",
        "daily_pick",
        "ledger",
        "snapshot_age_seconds",
        "score_snapshot",
        "checked_at",
    ):
        assert key in data
    assert set(data["ledger"]) >= {"required", "present", "gap"}


def test_last_resolver_tick_compat_shim_preserves_legacy_contract(monkeypatch):
    view = {
        "at": "2099-01-01T00:00:00+00:00",
        "status": "ok",
        "lifecycle": "ticking",
        "warming": False,
        "refresh_minutes": 15,
        "worker_peer": {"alive": True},
        "last_success_at": "2099-01-01T00:00:00+00:00",
        "liveness": {"status": "ok"},
    }
    monkeypatch.setattr(loop_health, "_resolver_liveness_view", lambda: view)
    monkeypatch.setattr(loop_health, "inline_worker_expected", lambda: False)
    monkeypatch.setattr(loop_health, "split_worker_v2_enabled", lambda: False)
    monkeypatch.setattr(loop_health, "is_worker_mode", lambda: True)

    result = loop_health._last_resolver_tick(soul_path="/ignored/legacy/path")

    assert result["at"] == view["at"]
    assert result["ok"] is True
    assert result["running"] is True
    assert result["lifecycle"] == "ticking"
    assert result["warming"] is False
    assert result["refresh_minutes"] == 15
    assert result["worker_peer"] == {"alive": True}


def test_resolver_state_cross_process_keeps_active_running_state(monkeypatch):
    view = {
        "at": "2099-01-01T00:00:00+00:00",
        "status": "ok",
        "lifecycle": "ticking",
        "warming": False,
        "refresh_minutes": 15,
        "worker_peer": {"alive": True},
    }
    monkeypatch.setattr(loop_health, "_resolver_liveness_view", lambda: view)
    monkeypatch.setattr(loop_health, "inline_worker_expected", lambda: False)
    monkeypatch.setattr(loop_health, "split_worker_v2_enabled", lambda: False)
    monkeypatch.setattr(loop_health, "is_worker_mode", lambda: True)
    monkeypatch.setattr(
        routes,
        "get_prediction_resolver_scheduler_state",
        lambda: {"running": False, "last_run_at": None},
    )

    result = routes._resolver_state_cross_process()

    assert result["source"] == "volume"
    assert result["running"] is True
    assert result["last_run_at"] == view["at"]
    assert result["last_run_ok"] is True
    assert result["refresh_minutes"] == 15
    assert result["worker_peer"] == view["worker_peer"]


def test_published_long_without_ledger_is_stalled(tmp_path, monkeypatch):
    daily = tmp_path / "daily_picks.json"
    preds = tmp_path / "predictions.json"
    _write_json(
        daily,
        [
            {
                "date": _today(),
                "action": "long",
                "pick": {"netuid": 58, "subnet": {"netuid": 58, "name": "Test"}},
            }
        ],
    )
    _write_json(preds, {"predictions": [], "resolved": [], "stats": {"pending": 0}})
    _seed_resolver_liveness(monkeypatch)
    report = build_learning_loop_health(
        daily_picks_path=str(daily),
        predictions_path=str(preds),
        soul_path=str(tmp_path / "missing_soul.json"),
    )
    assert report["ledger"]["required"] is True
    assert report["ledger"]["gap"] is True
    assert report["status"] == "stalled"


def test_hold_day_does_not_require_ledger(tmp_path, monkeypatch):
    daily = tmp_path / "daily_picks.json"
    preds = tmp_path / "predictions.json"
    _write_json(
        daily,
        [
            {
                "date": _today(),
                "action": "HOLD",
                "pick": None,
                "candidate": {"netuid": 36, "final_confidence": 0.35},
                "reason": "below gate",
            }
        ],
    )
    _write_json(preds, {"predictions": [], "resolved": [], "stats": {"pending": 0}})
    _seed_resolver_liveness(monkeypatch)
    report = build_learning_loop_health(
        daily_picks_path=str(daily),
        predictions_path=str(preds),
        soul_path=str(tmp_path / "missing_soul.json"),
    )
    assert report["ledger"]["required"] is False
    assert report["ledger"]["gap"] is False
    assert report["status"] == "ok"


def test_published_long_with_day_row_ok(tmp_path, monkeypatch):
    daily = tmp_path / "daily_picks.json"
    preds = tmp_path / "predictions.json"
    _write_json(
        daily,
        [
            {
                "date": _today(),
                "action": "BUY",
                "pick": {"subnet": {"netuid": 12, "name": "SN12"}},
            }
        ],
    )
    _write_json(
        preds,
        {
            "predictions": [
                {"netuid": 12, "horizon_type": "day", "status": "pending"},
            ],
            "resolved": [],
            "stats": {"pending": 1},
        },
    )
    _seed_resolver_liveness(monkeypatch)
    report = build_learning_loop_health(
        daily_picks_path=str(daily),
        predictions_path=str(preds),
        soul_path=str(tmp_path / "missing_soul.json"),
    )
    assert report["ledger"]["required"] is True
    assert report["ledger"]["present"] is True
    assert report["ledger"]["gap"] is False
    assert report["status"] == "ok"
    assert report["pending"] == 1


def test_inline_worker_alive_shows_resolver_status_ok(tmp_path, monkeypatch):
    """Web process must see fresh resolver tracker status when worker is alive."""
    monkeypatch.setenv("INLINE_WORKER", "1")
    monkeypatch.setenv("RUN_MODE", "web")
    daily = tmp_path / "daily_picks.json"
    preds = tmp_path / "predictions.json"
    soul = tmp_path / "soul_map.json"
    tick = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    _write_json(daily, [{"date": _today(), "action": "HOLD", "pick": None}])
    _write_json(preds, {"predictions": [], "resolved": [], "stats": {"pending": 0}})
    _seed_resolver_liveness(monkeypatch)
    monkeypatch.setattr("internal.worker_heartbeat.is_alive", lambda max_age_seconds=180: True)
    monkeypatch.setattr(
        "internal.worker_heartbeat.read_heartbeat",
        lambda: {"ts": tick, "run_mode": "worker"},
    )
    report = build_learning_loop_health(
        daily_picks_path=str(daily),
        predictions_path=str(preds),
        soul_path=str(soul),
    )
    assert report["resolver"]["status"] == "ok"
    assert report["resolver"]["last_success_at"] is not None
    assert report["worker_peer"]["alive"] is True
    assert report["status"] == "ok"


def test_inline_worker_alive_stale_tick_shows_resolver_not_ok(tmp_path, monkeypatch):
    """Stale tracker success must not read ok just because worker heartbeat is alive."""
    from datetime import timedelta

    monkeypatch.setenv("INLINE_WORKER", "1")
    monkeypatch.setenv("RUN_MODE", "web")
    daily = tmp_path / "daily_picks.json"
    preds = tmp_path / "predictions.json"
    soul = tmp_path / "soul_map.json"
    now = datetime.now(timezone.utc)
    old_tick = (now - timedelta(hours=3)).isoformat().replace("+00:00", "Z")
    fresh_hb = now.isoformat().replace("+00:00", "Z")
    _write_json(daily, [{"date": _today(), "action": "HOLD", "pick": None}])
    _write_json(preds, {"predictions": [], "resolved": [], "stats": {"pending": 0}})
    _seed_resolver_liveness(monkeypatch, stale_seconds=3 * 3600)
    monkeypatch.setattr("internal.worker_heartbeat.is_alive", lambda max_age_seconds=180: True)
    monkeypatch.setattr(
        "internal.worker_heartbeat.read_heartbeat",
        lambda: {"ts": fresh_hb, "run_mode": "worker"},
    )
    report = build_learning_loop_health(
        daily_picks_path=str(daily),
        predictions_path=str(preds),
        soul_path=str(soul),
    )
    assert report["resolver"]["status"] == "stale"
    assert report["worker_peer"]["alive"] is True


def test_young_pending_not_stalled_without_watchdog(tmp_path, monkeypatch):
    from datetime import timedelta

    monkeypatch.setenv("INLINE_WORKER", "0")
    daily = tmp_path / "daily_picks.json"
    preds = tmp_path / "predictions.json"
    now = datetime.now(timezone.utc)
    future = (now + timedelta(hours=12)).isoformat().replace("+00:00", "Z")
    created = now.isoformat().replace("+00:00", "Z")
    _write_json(daily, [{"date": _today(), "action": "HOLD", "pick": None}])
    _write_json(
        preds,
        {
            "predictions": [
                {
                    "id": "p1",
                    "netuid": 5,
                    "horizon_type": "hour",
                    "horizon_hours": 24,
                    "created_at": created,
                    "resolve_at": future,
                },
            ],
            "resolved": [],
            "stats": {"pending": 1},
        },
    )
    _seed_resolver_liveness(monkeypatch)
    report = build_learning_loop_health(
        daily_picks_path=str(daily),
        predictions_path=str(preds),
        soul_path=str(tmp_path / "missing_soul.json"),
    )
    assert report["pending"] == 1
    assert report["watchdog"].get("warning") is not True
    assert report["status"] == "ok"


def test_restart_with_stale_tick_degraded_not_stalled(tmp_path, monkeypatch):
    from datetime import timedelta

    monkeypatch.setenv("INLINE_WORKER", "1")
    monkeypatch.setenv("RUN_MODE", "web")
    daily = tmp_path / "daily_picks.json"
    preds = tmp_path / "predictions.json"
    soul = tmp_path / "soul_map.json"
    now = datetime.now(timezone.utc)
    old_tick = (now - timedelta(hours=3)).isoformat().replace("+00:00", "Z")
    fresh_hb = now.isoformat().replace("+00:00", "Z")
    created = now.isoformat().replace("+00:00", "Z")
    future = (now + timedelta(hours=12)).isoformat().replace("+00:00", "Z")
    _write_json(daily, [{"date": _today(), "action": "HOLD", "pick": None}])
    _write_json(
        preds,
        {
            "predictions": [
                {
                    "id": "p1",
                    "netuid": 5,
                    "horizon_type": "hour",
                    "horizon_hours": 24,
                    "created_at": created,
                    "resolve_at": future,
                },
            ],
            "resolved": [],
            "stats": {"pending": 1},
        },
    )
    _seed_resolver_liveness(monkeypatch, stale_seconds=3 * 3600)
    monkeypatch.setattr("internal.worker_heartbeat.is_alive", lambda max_age_seconds=180: True)
    monkeypatch.setattr(
        "internal.worker_heartbeat.read_heartbeat",
        lambda: {"ts": fresh_hb, "run_mode": "worker"},
    )
    report = build_learning_loop_health(
        daily_picks_path=str(daily),
        predictions_path=str(preds),
        soul_path=str(soul),
    )
    assert report["status"] == "degraded"
    assert report["watchdog"].get("warning") is not True


def test_snapshot_age_from_soul_map_when_file_missing(tmp_path, monkeypatch):
    """Worker may log cycle to soul_map before score_snapshots.json flush."""
    soul = tmp_path / "soul_map.json"
    snap = tmp_path / "score_snapshots.json"
    tick = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    _write_json(
        soul,
        {
            "score_snapshot_scheduler": {
                "last_cycle": {"run_at": tick, "ok": True, "snapshots_written": 3},
            }
        },
    )
    daily = tmp_path / "daily_picks.json"
    preds = tmp_path / "predictions.json"
    _write_json(daily, [{"date": _today(), "action": "HOLD", "pick": None}])
    _write_json(preds, {"predictions": [], "resolved": [], "stats": {"pending": 0}})
    _seed_resolver_liveness(monkeypatch)
    report = build_learning_loop_health(
        daily_picks_path=str(daily),
        predictions_path=str(preds),
        snapshots_path=str(snap),
        soul_path=str(soul),
    )
    assert report["snapshot_age_seconds"] is not None
    assert report["snapshot_age_seconds"] < 120.0
    meta = report["score_snapshot"]
    assert meta["file_present"] is False
    assert meta["last_cycle"].get("run_at") == tick


def test_snapshot_stale_degraded_not_stalled(tmp_path, monkeypatch):
    """Worker alive past grace with no snapshot file → degraded, not stalled."""
    from datetime import timedelta

    monkeypatch.setenv("INLINE_WORKER", "1")
    monkeypatch.setenv("RUN_MODE", "web")
    monkeypatch.setenv("LEARNING_SNAPSHOT_BOOT_GRACE_SECONDS", "60")
    monkeypatch.setenv("LEARNING_SNAPSHOT_STALE_SECONDS", "120")
    daily = tmp_path / "daily_picks.json"
    preds = tmp_path / "predictions.json"
    soul = tmp_path / "soul_map.json"
    snap = tmp_path / "score_snapshots.json"
    now = datetime.now(timezone.utc)
    tick = now.isoformat().replace("+00:00", "Z")
    old_hb = (now - timedelta(hours=2)).isoformat().replace("+00:00", "Z")
    _write_json(daily, [{"date": _today(), "action": "HOLD", "pick": None}])
    _write_json(preds, {"predictions": [], "resolved": [], "stats": {"pending": 0}})
    _write_json(soul, {"score_snapshot_scheduler": {"last_cycle": {}}})
    _seed_resolver_liveness(monkeypatch)
    monkeypatch.setattr("internal.worker_heartbeat.is_alive", lambda max_age_seconds=180: True)
    monkeypatch.setattr(
        "internal.worker_heartbeat.read_heartbeat",
        lambda: {"ts": old_hb, "run_mode": "worker"},
    )
    monkeypatch.setattr(
        "internal.council.score_snapshots._enabled",
        lambda: True,
    )
    report = build_learning_loop_health(
        daily_picks_path=str(daily),
        predictions_path=str(preds),
        snapshots_path=str(snap),
        soul_path=str(soul),
    )
    assert report["status"] == "degraded"
    assert report["snapshot_age_seconds"] is None


def test_self_learning_not_started_from_boot_or_server():
    """LB-8 quarantine: message_intel SelfLearning must stay off prod hot path."""
    boot = Path("internal/background_boot.py").read_text(encoding="utf-8")
    server = Path("server.py").read_text(encoding="utf-8")
    assert "start_background_learning" not in boot
    assert "start_background_learning" not in server
    assert "SelfLearning" not in server
