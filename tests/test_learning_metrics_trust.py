"""§27-1 — learning-metrics exposes trust_banner for hydrate fallback."""

from fastapi.testclient import TestClient

from server import app


def test_learning_metrics_includes_trust_banner():
    client = TestClient(app)
    resp = client.get("/api/learning-metrics")
    assert resp.status_code == 200
    body = resp.json()
    assert "trust_banner" in body
    assert isinstance(body["trust_banner"], dict)
    assert "ready" in body["trust_banner"]
