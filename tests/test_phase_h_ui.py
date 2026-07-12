"""Phase H-full — premium UI cockpit (style.css, 13 sections, Chart.js, honest-empty)."""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from internal.analytics.cockpit_render import enrich_cockpit_sections_for_display
from server import app

PREMIUM_SECTIONS = (
    "technical-indicators",
    "scanner",
    "staking-yield",
    "top-picks",
    "kpi-strip",
    "council",
    "radar",
    "judges",
    "mind-map",
    "social",
    "chat",
    "learning-trail",
    "undervalued-radar",
)


@pytest.fixture
def client():
    return TestClient(app)


def test_index_links_style_css(client):
    html = client.get("/").text
    assert "/static/css/style.css" in html


def test_index_has_card_components(client):
    html = client.get("/").text
    assert 'class="card' in html
    assert html.count('class="card') >= 13


def test_index_no_markdown_heading_triple_hash(client):
    html = client.get("/").text
    assert "###" not in html


def test_index_renders_thirteen_premium_sections(client):
    html = client.get("/").text
    for section_id in PREMIUM_SECTIONS:
        assert f'data-premium-section="{section_id}"' in html
    assert html.count("data-premium-section=") >= 13


def test_index_includes_chartjs(client):
    html = client.get("/").text.lower()
    assert "chart.js" in html or "chart.umd" in html


def test_index_includes_premium_cockpit_js(client):
    html = client.get("/").text
    assert "/static/js/premium_cockpit.js" in html


def test_kpi_strip_shows_learning_metrics(client):
    html = client.get("/").text
    api = client.get("/api/learning-metrics").json()
    acc = round(float(api.get("accuracy", 0)) * 100, 1)
    assert "kpi-strip" in html or 'data-premium-section="kpi-strip"' in html
    if api.get("predictions_resolved", 0) > 0:
        assert f"{acc}%" in html or "Accuracy" in html


def test_learning_trail_honest_empty_or_rows(client):
    html = client.get("/").text
    assert 'data-premium-section="learning-trail"' in html
    assert "Trail" in html or "Predictions" in html
    assert "###" not in html


def test_mindmap_section_present(client):
    html = client.get("/").text
    assert 'data-premium-section="mind-map"' in html
    assert "/api/mindmap/graph" in html or "mindmap-graph" in html


def test_strip_markdown_headings_in_enrichment():
    payload = {
        "status": "success",
        "sections": [
            {
                "id": "learning_loop",
                "title": "Learning Loop",
                "summary": "### Bad heading\nReal text.",
                "metrics": {"accuracy": 0.315, "correct": 1, "wrong": 2, "pending": 0},
                "status": "live",
                "updated_at": "2026-07-11T00:00:00Z",
            }
        ],
    }
    enriched = enrich_cockpit_sections_for_display(payload)
    summary = enriched["sections"][0]["summary"]
    assert "###" not in summary
    assert "Bad heading" in summary
    assert enriched["sections"][0]["highlights"]["accuracy_pct"] == 31.5
