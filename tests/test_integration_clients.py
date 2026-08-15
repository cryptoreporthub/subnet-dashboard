"""Integration clients and enrichment (optional API keys)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from internal.integrations.clients import (
    chat_llm_targets,
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


def test_openrouter_is_first_llm_target(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "router-key")
    monkeypatch.delenv("CHUTES_API_KEY", raising=False)
    monkeypatch.delenv("THIRTY_SPOKES_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    with patch(
        "internal.integrations.clients._models_endpoint_ok",
        return_value=True,
    ):
        targets = chat_llm_targets()
    assert targets[0] == (
        "https://openrouter.ai/api/v1",
        "openai/gpt-4o-mini",
        "openrouter",
    )
