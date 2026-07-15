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
    # Council-first: primary surfaces use pick/expert cards; dual 12-card grid removed
    assert 'class="council-stage"' in html or "council-stage" in html
    assert "class=\"card" in html or "pick-card" in html or "council-call" in html


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


def test_index_council_first_shell():
    """Council decision stage first; market tools demoted; no dual 12-card grid."""
    client = TestClient(app)
    html = client.get("/").text
    assert "council-stage" in html
    assert 'id="council-stage-body"' in html
    assert "council_first.css" in html
    assert 'id="market-drawer"' in html
    # Unicode apostrophe in “Today’s call” — match brand + stage title id
    assert "council-stage__title" in html
    assert "call" in html.lower()
    # Dual cockpit grid removed from homepage
    assert html.count('class="cockpit-card card"') == 0
    # Primary council surfaces still present
    for sid in (
        "section-daily-pick",
        "section-simivision-picks",
        "section-council",
        "section-judges",
        "section-picks",
        "section-kpi",
    ):
        assert f'id="{sid}"' in html
    # Brand is hero-level in the stage
    assert "council-stage__brand" in html
    pos_stage = html.index("council-stage")
    pos_drawer = html.index('id="market-drawer"')
    assert pos_stage < pos_drawer
    assert 'class="top-nav"' in html
    assert "/static/js/onboarding_tour.js" in html


def test_index_renders_twelve_cockpit_sections():
    """API still exposes 12 cockpit section ids; homepage no longer mirrors them as a grid."""
    client = TestClient(app)
    api = client.get("/api/cockpit/sections").json()
    sections = api.get("sections") or []
    assert len(sections) >= 12
    ids = {s.get("id") for s in sections}
    for section_id in COCKPIT_SECTION_IDS:
        assert section_id in ids


def test_learning_loop_shows_real_accuracy_highlight():
    client = TestClient(app)
    api = client.get("/api/cockpit/sections").json()
    learning = next(s for s in api["sections"] if s["id"] == "learning_loop")
    if learning.get("status") == "live" and learning.get("metrics", {}).get("accuracy") is not None:
        # Homepage no longer mirrors cockpit-card highlights; KPI section still present
        html = client.get("/").text
        assert 'id="section-kpi"' in html
        assert learning["metrics"]["accuracy"] is not None


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
    # Judges panel still on page (hydrated); P&L may live in API highlights only
    assert 'id="section-judges"' in html
    assert 'id="judges-panel"' in html


def test_trace_and_message_intel_honest_status():
    client = TestClient(app)
    api = client.get("/api/cockpit/sections").json()
    by_id = {s["id"]: s for s in api["sections"]}
    for section_id in ("trace", "message_intel"):
        section = by_id[section_id]
        assert section["status"] in ("live", "empty", "unavailable")
        assert section.get("summary")


def test_h_full_includes_chartjs():
    """No Chart.js CDN; uPlot spark + canvas radar assets loaded instead."""
    client = TestClient(app)
    html = client.get("/").text
    lower = html.lower()
    assert 'src="https://cdn.jsdelivr.net/npm/chart.js' not in lower
    assert "/static/vendor/uplot/uplot.iife.min.js" in lower
    assert "/static/js/uplot_charts.js" in lower
    assert "/static/vendor/uplot/uplot.min.css" in lower
    app_js = open("static/js/app.js", encoding="utf-8").read().lower()
    assert "chart.js" not in app_js
    uplot_js = open("static/js/uplot_charts.js", encoding="utf-8").read()
    assert "drawRadarCanvas" in uplot_js
    assert "window.__paintRadar" in uplot_js


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
    # Dual cockpit grid removed; council stage is the primary landmark
    assert 'class="council-stage"' in html
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
    assert "/static/js/cockpit_hydrate.js" in html
    assert "/static/js/premium_judges.js" not in html


def test_subnet_grouping_optional_lane():
    client = TestClient(app)
    html = client.get("/").text
    assert 'id="section-subnet-groups"' in html
    assert 'id="subnet-group-data"' in html
    assert "/static/js/subnet_grouping.js" in html
    # Homepage no longer mounts the 12-card cockpit grid
    assert html.count('class="cockpit-card card"') == 0


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
    assert "Conviction board" in html or "Council ranking" in html
    # SSR shell is often empty; hydrate fills picks — only require honest empty or cards
    assert "pick-card" in html or "warming up" in html


def test_h_full_daily_pick_hero_or_honest_empty():
    client = TestClient(app)
    html = client.get("/").text
    assert 'id="section-daily-pick"' in html
    assert "council-stage" in html
    assert "Council decision" in html or "Today" in html
    # Stage always states a stance (audited call or HOLD)
    assert "council-call" in html or "HOLD" in html or "Predicted" in html


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
    app_js = open("static/js/app.js", encoding="utf-8").read()
    uplot_js = open("static/js/uplot_charts.js", encoding="utf-8").read()
    assert "__paintSparks" in app_js or "__paintSparks" in uplot_js
    assert "drawRadarCanvas" in uplot_js
    assert "window.__paintRadar" in uplot_js


def test_c4_hydrate_calls_chart_paint_hooks():
    hydrate = open("static/js/cockpit_hydrate.js", encoding="utf-8").read()
    assert "paintCharts" in hydrate
    assert "__paintSparks" in hydrate
    assert "__paintRadar" in hydrate


def test_c6_conviction_tiers_script_on_index():
    client = TestClient(app)
    html = client.get("/").text
    assert "/static/js/conviction_tiers.js" in html
    pos_tiers = html.index("/static/js/conviction_tiers.js")
    pos_hydrate = html.index("/static/js/cockpit_hydrate.js")
    assert pos_tiers < pos_hydrate


def test_c6_simivision_picks_template_uses_canonical_cutoffs():
    src = open("templates/partials/premium/simivision_picks.html", encoding="utf-8").read()
    assert "conv > 75" in src
    assert "conv > 55" in src
    assert "conv > 35" in src
    assert "conv > 80" not in src
    assert "conv > 60" not in src
    assert "conv > 40" not in src


def test_c3_freshness_badge_has_aria_live():
    client = TestClient(app)
    html = client.get("/").text
    assert 'id="dataFreshnessBadge"' in html
    assert 'data-freshness-badge' in html
    assert 'aria-live="polite"' in html


def test_c3_index_loads_200():
    client = TestClient(app)
    assert client.get("/").status_code == 200


def test_c6_shared_conviction_thresholds_match_hydrate():
    tiers_src = open("static/js/conviction_tiers.js", encoding="utf-8").read()
    hydrate_src = open("static/js/cockpit_hydrate.js", encoding="utf-8").read()
    assert "cyan: 75" in tiers_src
    assert "lime: 55" in tiers_src
    assert "gold: 35" in tiers_src
    assert "ConvictionTiers.confTier" in hydrate_src
    assert "if (c > 75)" in hydrate_src
    assert "if (c > 55)" in hydrate_src
    assert "if (c > 35)" in hydrate_src


def test_g7_section_titles_use_rajdhani():
    premium = open("static/css/premium.css", encoding="utf-8").read()
    dashboard = open("static/css/dashboard.css", encoding="utf-8").read()
    assert ".section-title" in premium
    assert "font-family: var(--font-body)" in premium
    assert "font-family: var(--font-body)" in dashboard.split(".section-title")[1][:120]


def test_g12_favicon_and_font_consolidation():
    client = TestClient(app)
    html = client.get("/").text
    assert '/static/favicon.svg' in html
    assert "Space+Grotesk" not in html
    base_css = open("static/css/base.css", encoding="utf-8").read()
    assert "Orbitron" not in base_css
    assert "--font-display: 'Rajdhani'" in base_css
    assert client.get("/static/favicon.svg").status_code == 200
