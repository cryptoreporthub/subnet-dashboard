"""Phase 2 SA4 — market pulse + predictions visual enhancements (Grok LOCK)."""


def test_pulse_strip_phase2_hooks():
    html = open("templates/partials/premium/pulse_strip.html", encoding="utf-8").read()
    css = open("static/css/ui.css", encoding="utf-8").read()
    assert "sr-pulse__breadth-halo" in html
    assert "sr-pulse__ratio-meter" in html
    assert "--pulse-up" in html
    assert "pulse-breadth-halo" in css
    assert "sr-pulse__ratio-meter" in css


def test_kpi_accuracy_gauge_hooks():
    html = open("templates/partials/premium/kpi.html", encoding="utf-8").read()
    js = open("static/js/cockpit_hydrate.js", encoding="utf-8").read()
    css = open("static/css/ui.css", encoding="utf-8").read()
    assert "kpi--accuracy-gauge" in html
    assert "kpi__gauge-ring" in html
    assert "--kpi-p" in html
    assert "kpi-accuracy-card" in js
    assert "setProperty('--kpi-p'" in js
    assert "kpi-gauge-fill" in css


def test_story_strip_phase2_hooks():
    html = open("templates/partials/premium/story_strip.html", encoding="utf-8").read()
    js = open("static/js/home_live_refresh.js", encoding="utf-8").read()
    css = open("static/css/ui.css", encoding="utf-8").read()
    assert "story-strip__item--enter" in html
    assert "--story-i" in html
    assert "story-strip__item--enter" in js
    assert "story-strip-enter" in css
    assert "story-strip__item--correct" in css
