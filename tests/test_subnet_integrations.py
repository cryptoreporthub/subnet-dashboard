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
    assert len(body["integrations"]) == 3
    assert body["target_minimum"] == 2
    slugs = {row["slug"] for row in body["integrations"]}
    assert slugs == {"desearch", "chutes", "ditto"}
    assert "synth" not in slugs


def test_ditto_always_connected(monkeypatch):
    monkeypatch.delenv("DITTO_BASE_URL", raising=False)

    def fake_probe(method, url, **kwargs):
        return True, 401, "unauthorized"

    with patch("internal.integrations.status._http_probe", side_effect=fake_probe):
        payload = build_integrations_status()
    ditto = next(r for r in payload["integrations"] if r["slug"] == "ditto")
    assert ditto["connected"] is True
    assert ditto["status"] == "connected"


def test_desearch_connected_with_key_and_reachable(monkeypatch):
    monkeypatch.setenv("DESEARCH_API_KEY", "test-key")

    def fake_probe(method, url, **kwargs):
        if "desearch.ai" in url and method == "GET":
            return True, 200, "ok"
        if "desearch.ai" in url:
            return True, 402, "payment required"
        return True, 401, ""

    with patch("internal.integrations.status._http_probe", side_effect=fake_probe):
        payload = build_integrations_status()
    desearch = next(r for r in payload["integrations"] if r["slug"] == "desearch")
    assert desearch["connected"] is True
    assert desearch["status"] == "connected"


def test_corner_markup_on_homepage():
    with TestClient(app) as client:
        html = client.get("/").text
    assert 'id="subnetIntegrationsCorner"' in html
    assert 'id="subnetIntegrationsBar"' in html
    assert "subnet_integrations.js" in html


def test_ready_for_launch_when_two_connected(monkeypatch):
    def fake_probe(method, url, **kwargs):
        if "heyditto" in url or "ditto" in url:
            return True, 200, "ok"
        if "chutes" in url:
            return True, 200, "ok"
        return True, 200, "ok"

    monkeypatch.setenv("DESEARCH_API_KEY", "k")

    with patch("internal.integrations.status._http_probe", side_effect=fake_probe):
        payload = build_integrations_status()
    assert payload["connected_count"] >= 2
    assert payload["ready_for_launch"] is True
