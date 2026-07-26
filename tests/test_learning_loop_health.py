"""Phase 0 — learning loop health + ledger contract guard."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from internal.learning.loop_health import build_learning_loop_health
from server import app


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


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
        "checked_at",
    ):
        assert key in data
    assert set(data["ledger"]) >= {"required", "present", "gap"}


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
    monkeypatch.setattr(
        "internal.learning.loop_health.get_prediction_resolver_scheduler_state",
        lambda: {
            "running": True,
            "last_run_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "last_run_ok": True,
            "refresh_minutes": 15,
        },
    )
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
    monkeypatch.setattr(
        "internal.learning.loop_health.get_prediction_resolver_scheduler_state",
        lambda: {
            "running": True,
            "last_run_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "last_run_ok": True,
            "refresh_minutes": 15,
        },
    )
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
    monkeypatch.setattr(
        "internal.learning.loop_health.get_prediction_resolver_scheduler_state",
        lambda: {
            "running": True,
            "last_run_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "last_run_ok": True,
            "refresh_minutes": 15,
        },
    )
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


def test_self_learning_not_started_from_boot_or_server():
    """LB-8 quarantine: message_intel SelfLearning must stay off prod hot path."""
    boot = Path("internal/background_boot.py").read_text(encoding="utf-8")
    server = Path("server.py").read_text(encoding="utf-8")
    assert "start_background_learning" not in boot
    assert "start_background_learning" not in server
    assert "SelfLearning" not in server
