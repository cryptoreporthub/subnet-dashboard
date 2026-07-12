"""Phase H — UI shell (Agent B): style.css, cockpit cards, premium H-full layout."""

from __future__ import annotations

import re

from fastapi.testclient import TestClient
from fastapi.templating import Jinja2Templates

from internal.analytics.cockpit_render import (
    enrich_cockpit_sections_for_display,
    load_cockpit_sections,
)
from internal.cockpit.sections import COCKPIT_SECTION_IDS
from server import _jinja_shorten, app, templates


H_FULL_SECTION_IDS = [
    "section-header",
    "section-hero",
    "section-summary",
    "section-picks",
    "section-undervalued",
    "section-indicators",
    "section-council",
    "section-predictions",
    "section-scenario-pump",
    "section-trail",
    "section-footer",
]


def test_index_links_style_css():
    client = TestClient(app)
    html = client.get("/").text
    assert '/static/css/style.css' in html


def test_index_has_card_class():
    client = TestClient(app)
    html = client.get("/").text
    assert 'class="cockpit-card card"' in html or 'class="card cockpit-card"' in html
    assert html.count('class="cockpit-card card"') == 12


def test_index_no_markdown_heading_triple_hash():
    client = TestClient(app)
    html = client.get("/").text
    assert "###" not in html


def test_index_renders_twelve_cockpit_sections():
    client = TestClient(app)
    html = client.get("/").text
    assert html.count('class="cockpit-card card"') == 12
    for section_id in COCKPIT_SECTION_IDS:
        assert f'data-section-id="{section_id}"' in html


def test_learning_loop_shows_real_accuracy_highlight():
    client = TestClient(app)
    html = client.get("/").text
    api = client.get("/api/cockpit/sections").json()
    learning = next(s for s in api["sections"] if s["id"] == "learning_loop")
    if learning.get("status") == "live" and learning.get("metrics", {}).get("accuracy") is not None:
        acc = round(float(learning["metrics"]["accuracy"]) * 100, 1)
        assert "cockpit-highlight" in html
        assert f"{acc}%" in html


def test_judges_shows_pnl_highlight_when_live():
    payload = load_cockpit_sections()
    judges = next(s for s in payload["sections"] if s["id"] == "judges")
    if judges.get("status") != "live":
        return
    highlights = judges.get("highlights") or {}
    if highlights.get("combined_pnl_pct") is None:
        return
    client = TestClient(app)
    html = client.get("/").text
    assert "Combined P&amp;L" in html or "Combined P&L" in html
    pnl = highlights["combined_pnl_pct"]
    assert f"{pnl:+.2f}" in html or f"{pnl:+.1f}" in html


def test_trace_and_message_intel_honest_status():
    client = TestClient(app)
    api = client.get("/api/cockpit/sections").json()
    by_id = {s["id"]: s for s in api["sections"]}
    for section_id in ("trace", "message_intel"):
        section = by_id[section_id]
        assert section["status"] in ("live", "empty", "unavailable")
        assert section.get("summary")
    html = client.get("/").text
    assert 'data-section-id="trace"' in html
    assert 'data-section-id="message_intel"' in html


def test_no_chartjs_in_h_thin_shell():
    client = TestClient(app)
    html = client.get("/").text.lower()
    assert "chart.js" not in html
    assert "chartjs" not in html


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


def test_cockpit_api_matches_display_enrichment():
    client = TestClient(app)
    raw = client.get("/api/cockpit/sections").json()
    display = load_cockpit_sections()
    assert len(raw["sections"]) == 12
    assert len(display["sections"]) == 12
    for raw_row, disp_row in zip(raw["sections"], display["sections"]):
        assert raw_row["id"] == disp_row["id"]
        if isinstance(disp_row.get("summary"), str):
            assert "###" not in disp_row["summary"]
            assert not re.search(r"^#{1,6}\s", disp_row["summary"], re.MULTILINE)


# --- Phase H-full acceptance tests (11) ---


def test_h_full_eleven_premium_section_ids():
    client = TestClient(app)
    html = client.get("/").text
    for section_id in H_FULL_SECTION_IDS:
        assert f'id="{section_id}"' in html, f"missing {section_id}"
    assert 'id="cockpit-heading"' in html
    assert 'id="mindmap-graph-root"' in html


def test_h_full_utc_clock_markup_and_app_js():
    client = TestClient(app)
    html = client.get("/").text
    assert 'id="utcClock"' in html
    assert 'class="utc-clock"' in html
    assert "/static/js/app.js" in html


def test_h_full_shorten_filter_registered_and_formats_volume():
    assert "shorten" in templates.env.filters
    assert _jinja_shorten(1_500_000) == "1.5M"
    assert _jinja_shorten(42_000) == "42.0K"
    assert _jinja_shorten(None) == "—"


def test_h_full_header_live_pill_and_data_source():
    client = TestClient(app)
    html = client.get("/").text
    assert 'class="live-pill"' in html
    assert "DATA SOURCE:" in html
    assert 'id="section-header"' in html


def test_h_full_hero_section_never_blank():
    client = TestClient(app)
    html = client.get("/").text
    assert 'id="section-hero"' in html
    assert "Hero Signal" in html
    assert "hero-card" in html or "warming up" in html


def test_h_full_summary_grid_with_kpi_or_warmup():
    client = TestClient(app)
    html = client.get("/").text
    assert 'id="section-summary"' in html
    assert "kpi-grid" in html or "warming up" in html


def test_h_full_picks_section_simivision_or_warmup():
    client = TestClient(app)
    html = client.get("/").text
    assert 'id="section-picks"' in html
    assert "SimiVision" in html or "convening" in html


def test_h_full_undervalued_and_indicators_warmup_messages():
    client = TestClient(app)
    html = client.get("/").text
    assert 'id="section-undervalued"' in html
    assert 'id="section-indicators"' in html
    assert "warming up" in html


def test_h_full_council_predictions_scenario_trail_sections():
    client = TestClient(app)
    html = client.get("/").text
    for sid in (
        "section-council",
        "section-predictions",
        "section-scenario-pump",
        "section-trail",
    ):
        assert f'id="{sid}"' in html
    assert "Council Weights" in html
    assert "Predictive Engine" in html
    assert "Scenario" in html and "Pump" in html
    assert "Learning Trail" in html


def test_h_full_footer_status_strip_counts():
    client = TestClient(app)
    html = client.get("/").text
    assert 'id="section-footer"' in html
    assert 'class="status"' in html
    assert "Subnets:" in html
    assert "Predictions:" in html


def test_h_full_no_canvas_elements():
    client = TestClient(app)
    html = client.get("/").text.lower()
    assert "<canvas" not in html


def test_index_links_style_css():
    client = TestClient(app)
    html = client.get("/").text
    assert '/static/css/style.css' in html


def test_index_has_card_class():
    client = TestClient(app)
    html = client.get("/").text
    assert 'class="cockpit-card card"' in html or 'class="card cockpit-card"' in html
    assert html.count('class="cockpit-card card"') == 12


def test_index_no_markdown_heading_triple_hash():
    client = TestClient(app)
    html = client.get("/").text
    assert "###" not in html


def test_index_renders_twelve_cockpit_sections():
    client = TestClient(app)
    html = client.get("/").text
    assert html.count('class="cockpit-card card"') == 12
    for section_id in COCKPIT_SECTION_IDS:
        assert f'data-section-id="{section_id}"' in html


def test_learning_loop_shows_real_accuracy_highlight():
    client = TestClient(app)
    html = client.get("/").text
    api = client.get("/api/cockpit/sections").json()
    learning = next(s for s in api["sections"] if s["id"] == "learning_loop")
    if learning.get("status") == "live" and learning.get("metrics", {}).get("accuracy") is not None:
        acc = round(float(learning["metrics"]["accuracy"]) * 100, 1)
        assert "cockpit-highlight" in html
        assert f"{acc}%" in html


def test_judges_shows_pnl_highlight_when_live():
    payload = load_cockpit_sections()
    judges = next(s for s in payload["sections"] if s["id"] == "judges")
    if judges.get("status") != "live":
        return
    highlights = judges.get("highlights") or {}
    if highlights.get("combined_pnl_pct") is None:
        return
    client = TestClient(app)
    html = client.get("/").text
    assert "Combined P&amp;L" in html or "Combined P&L" in html
    pnl = highlights["combined_pnl_pct"]
    assert f"{pnl:+.2f}" in html or f"{pnl:+.1f}" in html


def test_trace_and_message_intel_honest_status():
    client = TestClient(app)
    api = client.get("/api/cockpit/sections").json()
    by_id = {s["id"]: s for s in api["sections"]}
    for section_id in ("trace", "message_intel"):
        section = by_id[section_id]
        assert section["status"] in ("live", "empty", "unavailable")
        assert section.get("summary")
    html = client.get("/").text
    assert 'data-section-id="trace"' in html
    assert 'data-section-id="message_intel"' in html


def test_no_chartjs_in_h_thin_shell():
    client = TestClient(app)
    html = client.get("/").text.lower()
    assert "chart.js" not in html
    assert "chartjs" not in html


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


def test_cockpit_api_matches_display_enrichment():
    client = TestClient(app)
    raw = client.get("/api/cockpit/sections").json()
    display = load_cockpit_sections()
    assert len(raw["sections"]) == 12
    assert len(display["sections"]) == 12
    for raw_row, disp_row in zip(raw["sections"], display["sections"]):
        assert raw_row["id"] == disp_row["id"]
        if isinstance(disp_row.get("summary"), str):
            assert "###" not in disp_row["summary"]
            assert not re.search(r"^#{1,6}\s", disp_row["summary"], re.MULTILINE)
