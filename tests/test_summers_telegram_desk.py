"""SS-TG W0 — Subnet Summers Telegram desk placement + branding."""

from __future__ import annotations

from fastapi.testclient import TestClient

from server import app

client = TestClient(app)


def test_summers_desk_first_class_on_home():
    import server as srv

    srv._prime_emergency_home_html()
    html = client.get("/").text
    assert 'id="section-message-intel"' in html
    assert "Telegram pulse" in html
    assert "Subnet Summers" in html
    assert "SIMIVISION" in html
    assert "t.me/OfficialSubnetSummer" in html
    assert "message_intel_feed.js" in html
    assert "message-intel__hero" in html
    assert "message-intel__legend" in html
    assert "message-intel__week-top" in html
    assert "Comment of the week" in html
    assert "message-intel__sec-bar" in html
    assert "message-intel__sw--violet" in html
    assert "message-intel__flagship-chip" in html
    assert "FLAGSHIP" in html
    assert "Loading live feed" in html or "Warming up Telegram" in html

    # Must sit on the spine — not only inside the More intel drawer
    mi = html.find('id="section-message-intel"')
    ribs = html.find('id="intel-ribs"')
    assert mi != -1 and ribs != -1
    assert mi < ribs, "Telegram desk must appear before More intel drawer"


def test_summers_desk_js_renders_conviction():
    src = open("static/js/message_intel_feed.js", encoding="utf-8").read()
    assert "conv-pill" in src or "% conv" in src
    assert "parseEntities" in src
    assert "OfficialSubnetSummer" in src
    assert "message-intel__rail-node" in src
    assert "is-bull" in src
    assert "message-intel__f-conv--high" in src
    assert "renderWeekTopComment" in src
    assert "week_top_comment" in src
    assert "renderDivergence" in src
    assert "/api/message-intel/divergence" in src


def test_summers_listener_hydration_contracts():
    route_src = open("internal/share_pages/routes.py", encoding="utf-8").read()
    template_src = open("templates/listener.html", encoding="utf-8").read()
    assert 'conv_payload.get("items")' in route_src
    assert 'authors_payload.get("reaction_crowns")' in route_src
    assert "reaction_crowns[:6]" in template_src
    assert "/subnetsummers" in template_src


def test_summers_flagship_css_tokens():
    css = open("static/css/ui.css", encoding="utf-8").read()
    assert "--mi-green:" in css
    assert "--mi-blue:" in css
    assert "--mi-orange:" in css
    assert "--mi-violet:" in css
    # Compat: --mi-pink aliases onto violet after sitewide magenta→violet migration
    assert "--mi-pink: var(--mi-violet)" in css
    assert "--mi-yellow: #f5d547" in css
    assert "rgba(245, 213, 71, 0.72)" in css  # yellow flagship board border
    assert ".message-intel__flagship-chip" in css
    assert ".message-intel__rail-node" in css
    assert ".message-intel__sec-bar--green" in css
    assert "message-intel-wave" in css
    assert "message-intel-conv-glow" in css
    assert "message-intel__masthead" in css
    assert "message-intel__spotlight" in css
    assert "message-intel__pulse-stage" in css
    assert "message-intel-board-breathe" in css
    assert "message-intel-spotlight-gleam" in css


def test_summers_flagship_composition_hooks():
    html = open("templates/partials/premium/message_intel_feed.html", encoding="utf-8").read()
    assert "message-intel__masthead" in html
    assert "message-intel__pulse-stage" in html
    assert "message-intel__spotlight" in html
    assert "message-intel__crowns-drawer" in html
    # IDs preserved for hydrate
    for eid in (
        "message-intel-week-top",
        "message-intel-yesterday",
        "message-intel-feed",
        "message-intel-proof",
        "message-intel-hc-strip",
        "message-intel-crowns",
        "message-intel-divergence",
        "message-intel-divergence-body",
    ):
        assert f'id="{eid}"' in html
    assert "Telegram outcome stories" in html


def test_summers_divergence_mobile_and_keyboard_hooks():
    css = open("static/css/ui.css", encoding="utf-8").read()
    assert ".message-intel__divergence" in css
    assert ".message-intel__divergence-receipt:focus-visible" in css
    assert ".message-intel__divergence-head" in css