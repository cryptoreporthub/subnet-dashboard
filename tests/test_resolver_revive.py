"""Resolver scheduler in-place revive (loop stall guard strike 1)."""

from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import internal.council.resolver as resolver
import internal.council.resolver_scheduler as rs
import internal.council.weights as weights


def _iso(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


def test_revive_recycles_hung_scheduler_and_runs_once(tmp_path, monkeypatch):
    soul = tmp_path / "soul_map.json"
    preds = tmp_path / "predictions.json"
    soul.write_text("{}", encoding="utf-8")
    preds.write_text(json.dumps({"predictions": [], "resolved": [], "stats": {}}), encoding="utf-8")
    monkeypatch.setattr(weights, "SOUL_MAP_PATH", str(soul))
    monkeypatch.setattr(rs, "SOUL_MAP_PATH", str(soul))
    monkeypatch.setattr(resolver, "PREDICTIONS_PATH", str(preds))

    old_tick = _iso(datetime.now(timezone.utc) - timedelta(hours=4))
    soul.write_text(
        json.dumps(
            {
                "prediction_resolver_scheduler": {
                    "last_cycle": {"run_at": old_tick, "ok": True, "pending": 0},
                    "lifecycle": "stopped",
                }
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        rs,
        "_default_subnets",
        lambda: [{"netuid": 1}],
    )
    monkeypatch.setattr(
        resolver,
        "resolve_due_predictions",
        lambda *_a, **_k: {
            "resolved_now": [],
            "expired_now": [],
            "stats": {"pending": 0},
            "watchdog": {"warning": False, "pending_count": 0},
        },
    )
    monkeypatch.setattr(
        resolver,
        "expire_stale_predictions",
        lambda: {
            "expired_now": [],
            "stats": {"pending": 0},
            "watchdog": {"warning": False, "pending_count": 0},
        },
    )

    @contextmanager
    def _free_slot(_name):
        yield True

    monkeypatch.setattr("internal.heavy_job_gate.heavy_job_slot", _free_slot)

    rs.stop_prediction_resolver_scheduler()
    sched = rs.PredictionResolverScheduler(refresh_minutes=15)
    sched._active = True
    rs._scheduler = sched

    try:
        out = rs.revive_prediction_resolver_scheduler(force=True)
        assert out["recycled"] is True
        assert out["revived"] is True
        assert out["age_after"] is not None
        assert out["age_after"] < 60
        data = json.loads(soul.read_text(encoding="utf-8"))
        last = data["prediction_resolver_scheduler"]["last_cycle"]
        assert last.get("ok") is True
        assert last.get("lifecycle") in ("running", "ticking")
        assert data["prediction_resolver_scheduler"].get("lifecycle") in ("running", "ticking", "starting", "scheduled")
    finally:
        rs.stop_prediction_resolver_scheduler()


def test_revive_honest_when_tick_fresh(tmp_path, monkeypatch):
    soul = tmp_path / "soul_map.json"
    tick = _iso(datetime.now(timezone.utc))
    soul.write_text(
        json.dumps(
            {"prediction_resolver_scheduler": {"last_cycle": {"run_at": tick, "ok": True}}}
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(weights, "SOUL_MAP_PATH", str(soul))
    monkeypatch.setattr(rs, "SOUL_MAP_PATH", str(soul))
    try:
        out = rs.revive_prediction_resolver_scheduler()
        assert out["revived"] is False
        assert out.get("reason") == "tick_fresh"
    finally:
        rs.stop_prediction_resolver_scheduler()
