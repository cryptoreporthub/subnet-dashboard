"""Phase 2 SA2 — Telegram desk visual enhancements (Grok LOCK)."""


def test_message_intel_no_fontshare_link():
    html = open("templates/partials/premium/message_intel_feed.html", encoding="utf-8").read()
    assert "fontshare.com" not in html
    assert "cabinet-grotesk" not in html.lower()
    assert "chillax" not in html.lower()


def test_message_intel_phase2_js_hooks():
    js = open("static/js/message_intel_feed.js", encoding="utf-8").read()
    css = open("static/css/ui.css", encoding="utf-8").read()
    assert "renderSentimentGauge" in js
    assert "message-intel__sent-gauge" in js
    assert "message-intel__feed-row--enter" in js
    assert "message-intel__feed-row--hot" in js
    assert "--mi-i" in js
    assert ".message-intel__sent-gauge" in css
    assert "mi-sent-rim" in css
    assert "mi-feed-enter" in css
