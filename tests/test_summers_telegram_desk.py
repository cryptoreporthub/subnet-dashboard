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
    assert "message-intel__sec-bar" in html
    assert "message-intel__sw--pink" in html
    assert "message-intel__flagship-chip" in html
    assert "FLAGSHIP" in html

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


def test_summers_flagship_css_tokens():
    css = open("static/css/council_first.css", encoding="utf-8").read()
    assert "--mi-green:" in css
    assert "--mi-blue:" in css
    assert "--mi-orange:" in css
    assert "--mi-pink:" in css
    assert "--mi-yellow: #f5d547" in css
    assert "rgba(245, 213, 71, 0.72)" in css  # yellow flagship board border
    assert ".message-intel__flagship-chip" in css
    assert ".message-intel__rail-node" in css
    assert ".message-intel__sec-bar--green" in css
