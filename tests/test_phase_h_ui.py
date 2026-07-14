"""Phase H — UI shell + premium cockpit (style.css, Chart.js, 13 sections)."""

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
    "section-simivision-picks",
    "section-daily-pick",
    "section-indicators",
    "section-scanner",
    "section-signals",
    "section-alerts",
    "section-subnet-groups",
    "section-staking",
    "section-picks",
    "section-kpi",
    "section-council",
    "section-radar",
    "section-judges",
    "section-mindmap",
    "section-social",
    "section-chat",
    "section-trail",
    "section-undervalued",
]


def test_index_links_split_css():
    client = TestClient(app)
    html = client.get("/").text
    for name in ("base", "layout", "dashboard", "chat", "premium", "responsive"):
        assert f"/static/css/{name}.css" in html


def test_index_has_card_class():
    client = TestClient(app)
    html = client.get("/").text
    assert 'class="cockpit-card card"' in html or 'class="card cockpit-card"' in html
    assert html.count('class="cockpit-card card"') == 12


def test_index_no_markdown_heading_triple_hash():
    client = TestClient(app)
    html = client.get("/").text
    assert "###" not in html


def test_index_has_data_freshness_badge():
    client = TestClient(app)
    html = client.get("/").text
    assert 'id="dataFreshnessBadge"' in html
    assert "/static/js/data_freshness.js" in html


def test_data_freshness_api_shape():
    client = TestClient(app)
    resp = client.get("/api/data-freshness")
    assert resp.status_code == 200
    data = resp.json()
    assert "stale" in data
    assert "source" in data


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


def test_h_full_includes_chartjs():
    client = TestClient(app)
    html = client.get("/").text.lower()
    assert "chart.js" in html or "chart.umd.min.js" in html


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


# --- Phase H-full acceptance tests ---


def test_h_full_thirteen_premium_section_ids():
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


def test_h_full_kpi_strip_learning_metrics():
    client = TestClient(app)
    html = client.get("/").text
    assert 'id="section-kpi"' in html
    assert "kpi-strip" in html
    assert "Accuracy" in html


def test_h_full_picks_scanner_staking_sections():
    client = TestClient(app)
    html = client.get("/").text
    for sid in ("section-picks", "section-scanner", "section-staking"):
        assert f'id="{sid}"' in html


def test_h_full_council_radar_judges_chat_sections():
    client = TestClient(app)
    html = client.get("/").text
    for sid in ("section-council", "section-radar", "section-judges", "section-chat"):
        assert f'id="{sid}"' in html
    assert "chatLog" in html
    assert "radarChart" in html or "warming up" in html


def test_h_full_social_trail_undervalued_sections():
    client = TestClient(app)
    html = client.get("/").text
    for sid in ("section-social", "section-trail", "section-undervalued"):
        assert f'id="{sid}"' in html


def test_h_full_footer_status_strip_counts():
    client = TestClient(app)
    html = client.get("/").text
    assert 'id="section-footer"' in html
    assert 'class="status"' in html
    assert "Subnets:" in html
    assert "Predictions:" in html


def test_h_full_premium_scanner_and_judges_js():
    client = TestClient(app)
    html = client.get("/").text
    assert "/static/js/premium_scanner.js" in html
    assert "/static/js/premium_judges.js" in html


def test_subnet_grouping_optional_lane():
    client = TestClient(app)
    html = client.get("/").text
    assert 'id="section-subnet-groups"' in html
    assert 'id="subnet-group-data"' in html
    assert "/static/js/subnet_grouping.js" in html
    assert html.count('class="cockpit-card card"') == 12


def test_h_full_hero_market_snapshot_section():
    client = TestClient(app)
    html = client.get("/").text
    assert 'id="section-hero"' in html
    assert "Market Snapshot" in html
    assert "kpi-grid" in html or "kpi-cell" in html


def test_h_full_simivision_picks_or_honest_empty():
    client = TestClient(app)
    html = client.get("/").text
    assert 'id="section-simivision-picks"' in html
    assert "SimiVision Top Picks" in html
    sv = client.get("/api/simivision").json()
    if sv.get("data", {}).get("top"):
        assert "pick-card" in html
        assert "Conviction" in html
    else:
        assert "warming up" in html


def test_h_full_daily_pick_hero_or_honest_empty():
    client = TestClient(app)
    html = client.get("/").text
    assert 'id="section-daily-pick"' in html
    assert "Daily Pick" in html
    if 'class="hero-card"' in html:
        assert "Final Confidence" in html
    else:
        assert "warming up" in html or "No audited daily pick" in html


def test_phase_l_cockpit_signals_and_summary():
    client = TestClient(app)
    html = client.get("/").text
    assert 'id="section-signals"' in html
    assert 'id="signal-summary-root"' in html
    assert 'id="signals-feed-root"' in html
    assert "Council Signal Pipeline" in html
    if 'id="signal-summary-root"' in html and "Signal summary warming up" not in html:
        assert "Buy" in html
        assert "Sell" in html


def test_phase_l_cockpit_alerts_honest_empty_or_list():
    client = TestClient(app)
    html = client.get("/").text
    assert 'id="section-alerts"' in html
    assert 'id="alerts-feed-root"' in html
    assert "Threshold" in html or "Alerts" in html
    assert "No active alerts" in html or "pick-card" in html


def test_phase_l_premium_signals_js():
    client = TestClient(app)
    html = client.get("/").text
    assert "/static/js/premium_signals.js" in html
    assert 'id="signals-ws-status"' in html


def test_c4_cockpit_hydrate_script_on_index():
    client = TestClient(app)
    html = client.get("/").text
    assert "/static/js/cockpit_hydrate.js" in html
    assert "document.documentElement.dataset.hydrate='1'" in html or 'data-hydrate="1"' in html


def test_c4_app_js_exposes_chart_paint_hooks():
    hooks = open("static/js/app.js", encoding="utf-8").read()
    assert "window.__paintSparks" in hooks
    assert "window.__paintRadar" in hooks


def test_c4_hydrate_calls_chart_paint_hooks():
    hydrate = open("static/js/cockpit_hydrate.js", encoding="utf-8").read()
    assert "paintCharts" in hydrate
    assert "__paintSparks" in hydrate
    assert "__paintRadar" in hydrate
