"""Subnet integration status API and corner UI wiring."""

from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient

from internal.integrations.status import build_integrations_status
from server import app


def test_subnet_integrations_api_contract():
    with TestClient(app) as client:
        resp = client.get("/api/subnet-integrations")
    assert resp.status_code == 200
    body = resp.json()
    assert "integrations" in body
    assert len(body["integrations"]) >= 10
    assert body["target_minimum"] == 3
    slugs = {row["slug"] for row in body["integrations"]}
    assert slugs >= {
        "desearch",
        "synth",
        "chutes",
        "ditto",
        "numinous",
        "data_universe",
        "vanta",
        "readyai",
    }


def test_subnet_integration_signals_endpoint():
    with TestClient(app) as client:
        resp = client.get("/api/subnet-integrations/signals")
    assert resp.status_code == 200
    body = resp.json()
    assert "signals" in body
    assert "mood" in body
    assert "updated_at" in body


def test_numinous_connected_on_leaderboard_200(monkeypatch):
    def fake_probe(method, url, **kwargs):
        if "numinouslabs" in url:
            return True, 200, '{"results":[{"miner_uid":1,"weight":0.1}]}'
        return True, 401, ""

    with patch("internal.integrations.status._http_probe", side_effect=fake_probe):
        payload = build_integrations_status()
    num = next(r for r in payload["integrations"] if r["slug"] == "numinous")
    assert num["connected"] is True


def test_ditto_always_connected(monkeypatch):
    monkeypatch.delenv("DITTO_BASE_URL", raising=False)

    def fake_probe(method, url, **kwargs):
        return True, 401, "unauthorized"

    with patch("internal.integrations.status._http_probe", side_effect=fake_probe):
        payload = build_integrations_status()
    ditto = next(r for r in payload["integrations"] if r["slug"] == "ditto")
    assert ditto["connected"] is True
    assert ditto["status"] == "connected"


def test_synth_connected_with_key_and_200(monkeypatch):
    monkeypatch.setenv("SYNTH_API_KEY", "test-key")

    def fake_probe(method, url, **kwargs):
        if "synthdata" in url:
            return True, 200, '{"asset":"BTC"}'
        return True, 401, ""

    with patch("internal.integrations.status._http_probe", side_effect=fake_probe):
        payload = build_integrations_status()
    synth = next(r for r in payload["integrations"] if r["slug"] == "synth")
    assert synth["connected"] is True


def test_corner_markup_on_homepage():
    with TestClient(app) as client:
        html = client.get("/").text
    assert 'id="subnetIntegrationsCorner"' in html
    assert "subnet_integrations.js" in html


def test_ready_for_launch_when_three_connected(monkeypatch):
    def fake_probe(method, url, **kwargs):
        if "heyditto" in url or "ditto" in url:
            return True, 200, "ok"
        if "chutes" in url:
            return True, 200, "ok"
        if "synthdata" in url:
            return True, 200, "ok"
        return True, 200, "ok"

    monkeypatch.setenv("CHUTES_API_KEY", "k")
    monkeypatch.setenv("SYNTH_API_KEY", "k")
    monkeypatch.setenv("DESEARCH_API_KEY", "k")

    with patch("internal.integrations.status._http_probe", side_effect=fake_probe):
        payload = build_integrations_status()
    assert payload["connected_count"] >= 3
    assert payload["ready_for_launch"] is True
