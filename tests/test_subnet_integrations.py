"""Subnet integration status API and compact strip wiring."""

from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient

from internal.integrations.status import build_integrations_status, clear_status_cache
from server import app


def setup_function():
    clear_status_cache()


def test_subnet_integrations_api_contract():
    with TestClient(app) as client:
        resp = client.get("/api/subnet-integrations")
    assert resp.status_code == 200
    body = resp.json()
    assert "integrations" in body
    assert len(body["integrations"]) == 5
    assert body["integration_total"] == 5
    assert body["target_minimum"] == 3
    slugs = {row["slug"] for row in body["integrations"]}
    assert slugs == {"bittensor", "blockmachine", "desearch", "chutes", "ditto"}
    assert "synth" not in slugs
    finney = next(r for r in body["integrations"] if r["slug"] == "bittensor")
    assert finney["name"] == "Finney mainnet"
    assert finney["netuid"] is None


def test_ditto_always_connected(monkeypatch):
    monkeypatch.delenv("DITTO_BASE_URL", raising=False)

    def fake_probe(method, url, **kwargs):
        return True, 401, "unauthorized"

    with patch("internal.integrations.status._http_probe", side_effect=fake_probe):
        with patch("internal.integrations.status._rpc_chain_healthy", return_value=(True, "ok")):
            payload = build_integrations_status(force=True)
    ditto = next(r for r in payload["integrations"] if r["slug"] == "ditto")
    assert ditto["connected"] is True
    assert ditto["status"] == "connected"


def test_finney_and_blockmachine_connected_when_rpc_ok(monkeypatch):
    with patch("internal.integrations.status._rpc_chain_healthy", return_value=(True, "chain RPC ok")):
        with patch("internal.integrations.status._http_probe", return_value=(True, 401, "")):
            payload = build_integrations_status(force=True)
    finney = next(r for r in payload["integrations"] if r["slug"] == "bittensor")
    blockmachine = next(r for r in payload["integrations"] if r["slug"] == "blockmachine")
    assert finney["connected"] is True
    assert finney["name"] == "Finney mainnet"
    assert blockmachine["connected"] is True
    assert blockmachine["netuid"] == 19


def test_desearch_connected_with_key_and_reachable(monkeypatch):
    monkeypatch.setenv("DESEARCH_API_KEY", "test-key")

    def fake_probe(method, url, **kwargs):
        if "desearch.ai" in url and method == "GET":
            return True, 200, "ok"
        return True, 401, ""

    with patch("internal.integrations.status._http_probe", side_effect=fake_probe):
        with patch("internal.integrations.status._rpc_chain_healthy", return_value=(True, "ok")):
            payload = build_integrations_status(force=True)
    desearch = next(r for r in payload["integrations"] if r["slug"] == "desearch")
    assert desearch["connected"] is True
    assert desearch["status"] == "connected"


def test_chutes_falls_back_when_base_url_404(monkeypatch):
    monkeypatch.setenv("CHUTES_API_KEY", "test-key")
    monkeypatch.setenv("LLM_BASE_URL", "https://api.chutes.ai/v1")

    def fake_probe(method, url, **kwargs):
        if "api.chutes.ai" in url:
            return True, 404, "not found"
        if "llm.chutes.ai" in url:
            if kwargs.get("headers", {}).get("Authorization"):
                return True, 200, '{"data":[]}'
            return True, 200, '{"data":[]}'
        return True, 404, ""

    with patch("internal.integrations.status._http_probe", side_effect=fake_probe):
        with patch("internal.integrations.status._rpc_chain_healthy", return_value=(True, "ok")):
            payload = build_integrations_status(force=True)
    chutes = next(r for r in payload["integrations"] if r["slug"] == "chutes")
    assert chutes["connected"] is True
    assert chutes["status"] == "connected"


def test_strip_markup_on_homepage():
    with TestClient(app) as client:
        html = client.get("/").text
    assert 'id="subnetIntegrationsBar"' in html
    assert "subnet_integrations.js" in html
    assert "subnet-int-strip" in open("static/js/subnet_integrations.js").read()


def test_status_cache_returns_same_payload():
    with patch("internal.integrations.status._rpc_chain_healthy", return_value=(True, "ok")):
        with patch("internal.integrations.status._http_probe", return_value=(True, 200, "ok")):
            a = build_integrations_status(force=True)
            b = build_integrations_status()
    assert a["connected_count"] == b["connected_count"]
    assert b.get("cached") is True


def test_ready_for_launch_when_three_connected(monkeypatch):
    def fake_probe(method, url, **kwargs):
        if "heyditto" in url or "ditto" in url:
            return True, 200, "ok"
        if "chutes" in url:
            return True, 200, "ok"
        return True, 200, "ok"

    monkeypatch.setenv("DESEARCH_API_KEY", "k")

    with patch("internal.integrations.status._http_probe", side_effect=fake_probe):
        with patch("internal.integrations.status._rpc_chain_healthy", return_value=(True, "ok")):
            payload = build_integrations_status(force=True)
    assert payload["connected_count"] >= 3
    assert payload["ready_for_launch"] is True
