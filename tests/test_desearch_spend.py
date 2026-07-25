"""DeSearch billing header capture and spend ledger."""

from __future__ import annotations

from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from internal.integrations.desearch_spend import (
    get_spend_summary,
    parse_billing_headers,
    record_desearch_response,
)
from server import app


def test_parse_billing_headers_case_insensitive():
    headers = {
        "X-Desearch-Cost-Usd": "0.001",
        "x-desearch-usage-count": "10",
        "X-Desearch-Service": "ai_search",
        "X-Desearch-Currency": "USD",
    }
    out = parse_billing_headers(headers)
    assert out["cost_usd"] == 0.001
    assert out["usage_count"] == 10
    assert out["service"] == "ai_search"
    assert out["currency"] == "USD"


def test_record_desearch_response_accumulates(tmp_path, monkeypatch):
    monkeypatch.setenv("DESEARCH_SPEND_PATH", str(tmp_path / "spend.json"))

    def _resp(cost: str, usage: str, service: str = "web_search"):
        resp = MagicMock()
        resp.headers = {
            "X-Desearch-Cost-Usd": cost,
            "X-Desearch-Usage-Count": usage,
            "X-Desearch-Service": service,
        }
        resp.url = "https://api.desearch.ai/search"
        resp.status_code = 200
        return resp

    assert record_desearch_response(_resp("0.001", "10"), path="/search", label="t1")
    assert record_desearch_response(_resp("0.002", "20", "ai_search"), path="/ai", label="t2")

    summary = get_spend_summary(recent_limit=5)
    assert summary["total_usd"] == 0.003
    assert summary["total_items"] == 30
    assert summary["calls"] == 2
    assert summary["billable_calls"] == 2
    assert summary["by_service"]["web_search"] == 0.001
    assert summary["by_service"]["ai_search"] == 0.002
    assert len(summary["recent"]) == 2


def test_record_skips_missing_billing_headers(tmp_path, monkeypatch):
    monkeypatch.setenv("DESEARCH_SPEND_PATH", str(tmp_path / "spend.json"))
    resp = MagicMock(headers={}, url="", status_code=200)
    assert record_desearch_response(resp) is None
    assert get_spend_summary()["calls"] == 0


def test_desearch_spend_api(tmp_path, monkeypatch):
    monkeypatch.setenv("DESEARCH_SPEND_PATH", str(tmp_path / "spend.json"))
    resp = MagicMock()
    resp.headers = {
        "X-Desearch-Cost-Usd": "0.01",
        "X-Desearch-Usage-Count": "10",
        "X-Desearch-Service": "probe",
    }
    resp.url = "https://api.desearch.ai/health"
    resp.status_code = 200
    record_desearch_response(resp, label="probe")

    with TestClient(app) as client:
        api = client.get("/api/ops/desearch-spend?recent=5")
        integrations = client.get("/api/subnet-integrations")
    assert api.status_code == 200
    assert api.json()["total_usd"] == 0.01
    assert integrations.status_code == 200
    assert integrations.json()["desearch_spend"]["total_usd"] == 0.01
