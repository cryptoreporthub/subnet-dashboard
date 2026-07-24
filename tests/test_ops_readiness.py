"""§33 — production readiness probe."""

from fastapi.testclient import TestClient

from server import app

client = TestClient(app)


def test_ops_readiness_contract():
    resp = client.get("/api/ops/readiness")
    assert resp.status_code == 200
    body = resp.json()
    assert "ready" in body
    assert "issues" in body
    assert "learning" in body
    assert "resolver" in body
    assert "subnet_feed" in body
    assert "daily_pick" in body
    assert "next_levers" in body
    assert body.get("worker_mode") in ("web", "worker", "combined")


def test_ops_llm_cost_contract():
    resp = client.get("/api/ops/llm-cost")
    assert resp.status_code == 200
    body = resp.json()
    assert "totals" in body
    assert "rates_per_million" in body
    assert "recent" in body
    assert "averages_per_llm_call" in body


def test_data_freshness_effective_fields():
    resp = client.get("/api/data-freshness")
    assert resp.status_code == 200
    body = resp.json()
    assert "effective_source" in body
    assert "effective_total" in body
