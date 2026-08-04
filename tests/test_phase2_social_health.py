"""Phase 2 SA5 — social, health HUD, fonts, integrations (Grok LOCK)."""


def test_space_grotesk_font_tokens():
    css = open("static/css/base.css", encoding="utf-8").read()
    base = open("templates/base.html", encoding="utf-8").read()
    assert "Space Grotesk" in css
    assert "Rajdhani" not in css
    assert "Space+Grotesk" in base
    assert "Rajdhani" not in base


def test_social_phase2_hooks():
    html = open("templates/partials/premium/social.html", encoding="utf-8").read()
    js = open("static/js/social_sentiment.js", encoding="utf-8").read()
    css = open("static/css/ui.css", encoding="utf-8").read()
    assert "soc-card--{{ label }}" in html
    assert "soc-vol-track" in html
    assert "soc-card--enter" in html
    assert "soc-card--hot" in html
    assert "tierClass" in js
    assert "soc-vol-fill" in css


def test_ops_readiness_badge_renders():
    js = open("static/js/ops_readiness_badge.js", encoding="utf-8").read()
    css = open("static/css/ui.css", encoding="utf-8").read()
    assert "grade = 'READY'" in js or "grade = \"READY\"" in js
    assert "ops-readiness--degraded" in js
    assert "display: inline-flex !important" in css


def test_integrations_live_rail_hooks():
    js = open("static/js/subnet_integrations.js", encoding="utf-8").read()
    css = open("static/css/ui.css", encoding="utf-8").read()
    assert "rim-chroma" in js
    assert "subnet-int-strip--live" in css
    assert "subnet-int-stale-breathe" in css
