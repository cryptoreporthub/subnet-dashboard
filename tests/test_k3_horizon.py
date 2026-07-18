"""K3-6 — horizon selector (Now / 24h / 7d)."""

from __future__ import annotations

from internal.learning.dpick_horizon import (
    attach_horizon_views_to_daily_pick,
    build_horizon_views,
)
from internal.learning.dpick_horizon import _trend_lens_confidence as trend_adj


def test_trend_lens_confidence_bounds():
    assert trend_adj(70, 12.0, "LONG") == 72
    assert trend_adj(70, -12.0, "LONG") == 68
    assert trend_adj(70, None, "LONG") is None


def test_build_horizon_views_three_chips():
    day = {
        "pick": {
            "subnet": {"netuid": 14, "name": "SN14", "symbol": "T14"},
            "final_confidence": 0.78,
            "action": "long",
        }
    }
    hour = {
        "subnet": {"netuid": 82, "name": "MinoS", "symbol": "MINO"},
        "final_confidence": 0.65,
        "action": "long",
    }
    subnets = [{"netuid": 14, "price_change_7d": 8.5}]
    out = build_horizon_views(day, hour, subnets)
    assert out["default"] == "24h"
    assert out["chips"] == ["now", "24h", "7d"]
    assert out["views"]["now"]["subnet"]["netuid"] == 82
    assert out["views"]["24h"]["subnet"]["netuid"] == 14
    assert out["views"]["7d"]["lens"] == "trend"
    assert out["views"]["7d"]["note"] == "Trend lens — not graded"
    assert out["views"]["7d"]["conviction"] >= 70


def test_build_horizon_views_omits_7d_without_price():
    day = {
        "pick": {
            "subnet": {"netuid": 1, "name": "A"},
            "final_confidence": 0.5,
        }
    }
    hour = {"subnet": {"netuid": 2, "name": "B"}, "final_confidence": 0.4}
    out = build_horizon_views(day, hour, [{"netuid": 1}])
    assert "7d" not in out["chips"]


def test_attach_horizon_views_on_daily_pick():
    payload = {
        "pick": {
            "subnet": {"netuid": 3, "name": "C"},
            "final_confidence": 0.6,
            "prediction": {"resolve_at": "2026-07-19T00:00:00Z", "horizon_hours": 4},
        }
    }
    subnets = [{"netuid": 3, "price_change_7d": 2.0}]
    out = attach_horizon_views_to_daily_pick(payload, subnets, {})
    assert "horizon_views" in out
    assert out["horizon_active"] == "24h"


def test_home_renders_horizon_chips():
    from fastapi.testclient import TestClient

    from server import app

    with TestClient(app) as client:
        html = client.get("/").text
    assert "k3-horizon-chips" in html or "k3-horizon-chip" in html
