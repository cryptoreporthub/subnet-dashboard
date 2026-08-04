"""Phase 2 SA3 — picks + radar visual enhancements (Grok LOCK)."""


def test_picks_phase2_hooks():
    html = open("templates/partials/premium/picks.html", encoding="utf-8").read()
    js = open("static/js/cockpit_hydrate.js", encoding="utf-8").read()
    css = open("static/css/ui.css", encoding="utf-8").read()
    assert "pick-card--reveal" in html
    assert "pick-card--lead-hour" in html
    assert "pick-card--lead-day" in html
    assert "--pick-i" in html
    assert "pick-card--reveal" in js
    assert "pick-card--lead-" in js
    assert "pick-conf-reveal" in css
    assert "pick-card--lead" in css


def test_radar_phase2_hooks():
    html = open("templates/partials/premium/radar.html", encoding="utf-8").read()
    js = open("static/js/cockpit_hydrate.js", encoding="utf-8").read()
    css = open("static/css/ui.css", encoding="utf-8").read()
    assert "chart-canvas-wrap--radar" in html
    assert "radar-item--enter" in html
    assert "radar-item--lead" in html
    assert "radar-item__bar" in html
    assert "chart-canvas-wrap--radar" in js
    assert "radar-item--enter" in js
    assert "radar-frame-spin" in css
    assert "radar-item__bar--up" in css
