"""Phase 2 SA2 — Telegram desk visual enhancements (Grok LOCK)."""

import re


def test_message_intel_no_fontshare_link():
    html = open("templates/partials/premium/message_intel_feed.html", encoding="utf-8").read()
    assert "fontshare.com" not in html
    assert "cabinet-grotesk" not in html.lower()
    assert "chillax" not in html.lower()


def test_message_intel_phase2_js_hooks():
    js = open("static/js/message_intel_feed.js", encoding="utf-8").read()
    css = open("static/css/ui.css", encoding="utf-8").read()
    assert js.count("function pulseModeFromHash()") == 1
    assert js.count("function setPulseMode(mode, opts)") == 1
    assert js.count("function bindPulseModes()") == 1
    assert "renderSentimentGauge" in js
    assert "message-intel__sent-gauge" in js
    assert "message-intel__feed-row--enter" in js
    assert "message-intel__feed-row--hot" in js
    assert "--mi-i" in js
    assert ".message-intel__sent-gauge" in css
    assert "mi-sent-rim" in css
    assert "mi-feed-enter" in css


def test_message_intel_ssr_populates_from_context():
    html = open("templates/partials/premium/message_intel_feed.html", encoding="utf-8").read()
    assert "message_intel_ssr_macros" in html
    assert "feed_rows(mi_messages)" in html
    assert "trend_rows(mi_trending" in html
    assert "champion_rows(mi_authors)" in html
    assert 'aria-busy="{{ \'false\' if mi_messages else \'true\' }}"' in html


def test_message_intel_home_loop_has_accessible_listen_learn_rank_serve_panes():
    html = open("templates/partials/premium/message_intel_feed.html", encoding="utf-8").read()
    js = open("static/js/message_intel_feed.js", encoding="utf-8").read()
    for mode in ("listen", "learn", "rank", "serve"):
        assert f'data-pulse-mode="{mode}"' in html
        pane_id = f"message-intel-pane-{mode}"
        assert html.count(f'id="{pane_id}"') == 1
        assert html.count(f'data-pulse-pane="{mode}"') == 1
        assert html.count(f'aria-controls="{pane_id}"') == 1
        pane = re.search(rf'<[^>]+id="{pane_id}"[^>]*>', html)
        assert pane is not None
        assert 'role="tabpanel"' in pane.group(0)
        assert f'aria-labelledby="pulse-tab-{mode}"' in pane.group(0)
    assert 'role="tablist"' in html
    assert html.count('role="tabpanel"') == 4
    assert "bindPulseModes" in js
    assert "pulseModeFromHash" in js


def test_future_wallet_and_command_surfaces_are_visible_but_locked():
    html = open("templates/partials/premium/message_intel_feed.html", encoding="utf-8").read()
    assert 'id="message-intel-wallet-card"' in html
    assert "Connect wallet" in html
    assert 'id="message-intel-commands-card"' in html
    assert "/trending" in html
    assert "LOCKED · COMING SOON" in html
