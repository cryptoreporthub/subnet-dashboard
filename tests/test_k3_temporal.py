"""K3-4 — temporal confidence ring data + UI."""

from datetime import datetime, timedelta, timezone

from internal.learning.dpick_temporal import (
    attach_temporal_to_daily_pick,
    build_temporal_block,
    ring_state_for,
)


def test_ring_state_thresholds():
    now = datetime.now(timezone.utc)
    assert ring_state_for(now + timedelta(hours=4), now) == "fresh"
    assert ring_state_for(now + timedelta(hours=2), now - timedelta(hours=2)) == "aging"
    assert ring_state_for(now + timedelta(minutes=20), now - timedelta(hours=3, minutes=40)) == "expiring"
    assert ring_state_for(now - timedelta(minutes=1), now - timedelta(hours=4)) == "resolved"


def test_attach_temporal_from_prediction():
    payload = {
        "pick": {
            "subnet": {"netuid": 1, "name": "Alpha"},
            "prediction": {
                "resolve_at": (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat().replace("+00:00", "Z"),
                "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "horizon_hours": 4,
            },
        }
    }
    out = attach_temporal_to_daily_pick(payload)
    assert out.get("resolve_at")
    assert out.get("temporal_badge", "").startswith("LIVE")
    assert out.get("ring_state") in ("fresh", "aging", "expiring")


def test_home_renders_temporal_badge():
    from fastapi.testclient import TestClient

    from server import app

    with TestClient(app) as client:
        html = client.get("/").text
    assert "k3-temporal-badge" in html
    assert "k3-ring--" in html
