"""Phase 0 — reconnect smoke: Tier-1 APIs must not 422."""

from __future__ import annotations

from fastapi.testclient import TestClient

from server import app

_TIER1_ROUTES = [
    ("GET", "/health"),
    ("GET", "/api/pump-alerts"),
    ("GET", "/api/daily-pick"),
    ("GET", "/api/subnets?limit=1"),
    ("GET", "/api/ops/readiness"),
    ("GET", "/api/learning/stats"),
]


def test_tier1_routes_not_422():
    with TestClient(app) as client:
        for method, path in _TIER1_ROUTES:
            resp = client.request(method, path)
            assert resp.status_code != 422, f"{method} {path} returned 422: {resp.text[:200]}"
