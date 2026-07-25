"""Integration clients and enrichment (optional API keys)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from internal.integrations.clients import (
    chutes_configured,
    desearch_subnet_snippet,
)
from internal.integrations.enrichment import integration_evidence_drivers


def test_desearch_snippet_without_key():
    assert desearch_subnet_snippet(1, name="Alpha") is None


def test_desearch_snippet_with_key(monkeypatch):
    monkeypatch.setenv("DESEARCH_API_KEY", "k")

    def fake_request(method, url, **kwargs):
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = [{"title": "Subnet alpha momentum rising"}]
        return resp

    with patch("internal.integrations.clients.desearch_request", side_effect=fake_request):
        with patch("internal.integrations.clients._cache", {}):
            out = desearch_subnet_snippet(1, name="Alpha")
    assert out == "Subnet alpha momentum rising"


def test_enrichment_merges_drivers(monkeypatch):
    monkeypatch.setenv("DESEARCH_API_KEY", "k")

    with patch(
        "internal.integrations.enrichment.clients.desearch_subnet_snippet",
        return_value="Hot thread on SN1",
    ):
        rows = integration_evidence_drivers(1, "Alpha")
    assert len(rows) == 1
    assert rows[0]["tag"] == "social"


def test_chutes_configured():
    assert chutes_configured() is False
