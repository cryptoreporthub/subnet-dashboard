"""Security headers middleware (audit phase 2)."""

from fastapi.testclient import TestClient

from server import app


def test_home_includes_security_headers():
    with TestClient(app) as client:
        r = client.get("/")
    assert r.status_code == 200
    assert r.headers.get("x-content-type-options") == "nosniff"
    assert r.headers.get("x-frame-options") == "SAMEORIGIN"
    assert r.headers.get("referrer-policy") == "strict-origin-when-cross-origin"
    assert "strict-transport-security" in r.headers
    assert "content-security-policy-report-only" in r.headers


def test_bailout_health_includes_security_headers():
    with TestClient(app) as client:
        r = client.get("/health")
    assert r.status_code == 200
    assert r.headers.get("x-content-type-options") == "nosniff"
    assert "strict-transport-security" in r.headers


def test_ops_live_bailout_includes_security_headers():
    with TestClient(app) as client:
        r = client.get("/api/ops/live")
    assert r.status_code == 200
    assert r.headers.get("x-content-type-options") == "nosniff"
