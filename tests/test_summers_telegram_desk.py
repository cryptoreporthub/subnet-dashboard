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
    assert "glass-card" in html
    assert "message-intel__pulsar" in html
    assert "message-intel__sky" in html
    assert "FLAGSHIP" not in html
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
    assert "renderHeroStats" in src
    assert "renderInterceptWave" in src
    assert "renderTrendingSky" in src
    assert "pingPulsar" in src
    assert "message-intel__conv-ring" in src
    assert "renderHeartbeat" in src
    assert "renderChatterPower" in src
    assert "too few graded calls to trust" in src
    assert "pollNetFlow" in src


def test_summers_flagship_css_tokens():
    css = open("static/css/ui.css", encoding="utf-8").read()
    assert "--mi-green:" in css
    assert "--mi-blue:" in css
    assert "--mi-orange:" in css
    assert "--mi-violet:" in css
    # Compat: --mi-pink aliases onto violet after sitewide magenta→violet migration
    assert "--mi-pink: var(--mi-violet)" in css
    assert "--mi-yellow:" in css
    assert "--glass-fill-card" in css
    assert ".message-intel__pulsar" in css
    assert ".message-intel__sky" in css
    assert ".message-intel__conv-ring" in css
    assert ".message-intel__rail-node" in css
    assert ".message-intel__sec-bar--green" in css
    assert "message-intel-wave" in css
    assert "message-intel-conv-glow" in css
    assert "message-intel__masthead" in css
    assert "message-intel__spotlight" in css
    assert "message-intel__pulse-stage" in css
    assert "message-intel-board-breathe" in css
    assert "message-intel-spotlight-gleam" in css
    assert ".message-intel__bay" in css
    assert ".message-intel__instrument" in css
    assert ".message-intel__heartbeat" in css
    assert ".message-intel__loop" in css
    assert ".message-intel__tile--orbit" in css
    assert ".message-intel__sky-track--1" in css
    assert ".message-intel__sky-carrier" in css
    assert ".message-intel__rail { display: contents; }" in css
    assert ".message-intel__cell { display: none; }" not in css
    # Cosmic glass: desk must stay transparent so the site sky reads through
    assert "rgba(6,10,8,0.96)" not in css.split(".message-intel--v2 {", 1)[-1].split("}", 1)[0]


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
    assert "message-intel__pulsar" in html
    assert "message-intel__sky-track" in html
    assert "message-intel__sky-carrier" in html
    assert "message-intel__rail" in html
    assert 'id="message-intel-sky"' in html
    assert "hidden" not in html.split('id="message-intel-sky"', 1)[1].split(">", 1)[0]
    assert "message-intel__bay" in html
    assert "message-intel__heartbeat" in html
    assert "message-intel__loop" in html
    assert "Chatter Power" in html
    assert "message-intel__instrument" in html
    assert "message-intel__zones" not in html
    assert "mi-zone-feed" not in html
    assert 'id="message-intel-flow"' in html
    assert 'id="message-intel-callers-body"' in html
    assert 'id="message-intel-power"' in html
    assert "/rank" in html
    assert "/who" in html
    assert "message-intel__conv-ring" in open(
        "templates/partials/premium/message_intel_ssr_macros.html", encoding="utf-8"
    ).read()


def test_listener_share_page_composition():
    html = open("templates/listener.html", encoding="utf-8").read()
    css = open("static/css/listener.css", encoding="utf-8").read()
    assert "lsn-intercept" in html
    assert "lsn-title" in html
    assert "lsn-bay" in html
    assert "lsn-loop" in html
    assert "Chatter Power" in html
    assert "/rank" in html
    assert "/who" in html
    assert "lsn-orbit" in html
    assert "lsn-orbit__track" in html
    assert "lsn-rail" in html
    assert ".lsn-orbit" in css
    assert ".lsn-rail{display:contents}" in css.replace(" ", "")
    assert "lsn-zones" not in html
    assert "lsn-zone-feed" not in html
    assert "Telegram pulse" in html
    assert "Trending orbit" in html
    assert "Syne" in html
    assert "Space+Grotesk" in html
    assert "wallet" not in html.lower()
    assert "lsn-vault" not in html
    assert ".lsn-intercept" in css
    assert "--lsn-font-brand:'Syne'" in css.replace(" ", "")
    resp = client.get("/listener")
    assert resp.status_code == 200
    body = resp.text
    assert "lsn-intercept" in body
    assert "Trending orbit" in body


def test_summers_divergence_mobile_and_keyboard_hooks():
    css = open("static/css/ui.css", encoding="utf-8").read()
    assert ".message-intel__divergence" in css
    assert ".message-intel__divergence-receipt:focus-visible" in css
    assert ".message-intel__divergence-head" in css