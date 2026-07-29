"""Phase LA — daily-pick meta + pending must not masquerade as fresh pick."""

from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient


def test_daily_pick_includes_generated_at_meta():
    with patch("internal.council.daily_pick_engine._find_today") as find_today:
        find_today.return_value = {
            "status": "ok",
            "action": "HOLD",
            "timestamp_utc": "2026-07-29T12:00:00Z",
            "pick": None,
            "candidate": {"subnet": {"netuid": 5, "name": "Test"}},
        }
        from server import app

        client = TestClient(app)
        body = client.get("/api/daily-pick").json()
    assert body.get("generated_at") == "2026-07-29T12:00:00Z"
    meta = body.get("_meta") or {}
    assert meta.get("generated_at") == "2026-07-29T12:00:00Z"
    assert meta.get("data_source") in ("local", "volume")


def test_daily_pick_pending_has_status_and_stale_meta():
    with patch("internal.council.daily_pick_engine._find_today", return_value=None):
        with patch("internal.council.daily_pick_engine._load", return_value=[]):
            from server import app

            client = TestClient(app)
            body = client.get("/api/daily-pick").json()
    assert body.get("status") == "pending"
    assert body.get("action") == "HOLD"
    assert body.get("pick") is None
    meta = body.get("_meta") or {}
    assert meta.get("stale") is False
