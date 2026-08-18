"""SS-TG W0 — Subnet Summers Telegram desk placement + branding."""

from __future__ import annotations

from fastapi.testclient import TestClient

from server import app

client = TestClient(app)


def test_hud_unsticks_before_telegram():
    """Council/Weighing/Lead/Focus/Proof stick only through the front, then peel off."""
    html = open("templates/partials/premium_cockpit.html", encoding="utf-8").read()
    start = html.find('<div class="sr-front">')
    telegram = html.find('include "partials/premium/message_intel_feed.html"')
    assert start != -1 and telegram != -1 and start < telegram
    inner, rest = html[start:].split("</div>", 1)
    assert 'include "partials/premium/header.html"' in inner
    assert 'include "partials/premium/pump_alert_scan.html"' in inner
    assert 'include "partials/premium/message_intel_feed.html"' not in inner
    assert 'include "partials/premium/message_intel_feed.html"' in rest


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
    assert 'rank === 1 ? 30 : rank === 2 ? 22 : 15' in src
    assert "awaiting signal" in src
    assert "pingPulsar" in src
    assert "message-intel__conv-ring" in src
    assert "renderHeartbeat" in src
    assert "renderChatterPower" in src
    assert "too few graded calls to trust" in src
    assert "pollNetFlow" in src
    assert "bindPulseModes" in src


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
    assert ".message-intel__full-desk" in css
    assert ".message-intel__mode" in css
    assert ".message-intel__tile--orbit" in css
    assert ".message-intel__sky-track--1" in css
    assert ".message-intel__sky-carrier" in css
    assert ".message-intel__hall" in css
    assert ".message-intel__hall { display: contents; }" in css
    assert '[data-rank="1"] { --spin: 26s; --r: 21.43%;' in css
    assert ".message-intel__sky-legend" in css
    assert ".message-intel__cell { display: none; }" not in css
    # Cosmic glass: desk must stay transparent so the site sky reads through
    assert "rgba(6,10,8,0.96)" not in css.split(".message-intel--v2 {", 1)[-1].split("}", 1)[0]
    assert "minmax(0, 1.55fr) minmax(260px, 0.95fr)" not in css
    assert "grid-template-columns: 1.15fr 1fr" not in css
    learn_grid = css.split(".message-intel__learn-dual-grid {", 1)[1].split("}", 1)[0]
    assert "grid-template-columns: 1fr" in learn_grid
    assert "1fr 1fr" not in learn_grid
    # Shared site sky — desk mock palette must not retint .cosmic-sky
    sky = css.split(".cosmic-sky {", 1)[1].split("}", 1)[0]
    assert "#060814" not in sky
    # Visualizer floats on that sky — no navy card fill; SN chips stay opaque
    vis = css.split(".message-intel--v2 .message-intel__visualizer-card {", 1)[1].split("}", 1)[0]
    assert "background: none" in vis
    assert "rgba(8, 12, 28, 0.92)" not in vis
    vis_glass = css.split(".message-intel--v2 .message-intel__visualizer-card.glass-card {", 1)[1].split("}", 1)[0]
    assert "rgba(8, 12, 28, 0.92)" not in vis_glass
    badge = css.split(".message-intel--v2 .message-intel__sky-badge {", 1)[1].split("}", 1)[0]
    assert "rgba(8, 9, 17, 0.82)" in badge
    assert "backdrop-filter" not in badge


def test_summers_flagship_composition_hooks():
    html = open("templates/partials/premium/message_intel_feed.html", encoding="utf-8").read()
    assert 'include "partials/premium/cosmic_resonance_core.html"' in html
    core = open("templates/partials/premium/cosmic_resonance_core.html", encoding="utf-8").read()
    assert html.find('include "partials/premium/cosmic_resonance_core.html"') < html.find('role="tablist"'), (
        "Cosmic Resonance Core must sit at the top of the Telegram section, before LISTEN/LEARN/RANK/SERVE"
    )
    assert 'message-intel__visualizer-card glass-card' not in html
    assert html.find("OPEN FULL DESK") < html.find(">LISTEN<")
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
    assert "message-intel__sky-track" in core
    assert "message-intel__sky-hub" in core
    assert "message-intel__hall" in html
    assert "message-intel__rail\"" not in html
    assert 'id="message-intel-sky"' in core
    assert "message-intel__sky-legend" in core
    assert "closer = higher rank" in core
    assert "bigger = higher rank" in core
    assert "message-intel__bay" in html
    assert "message-intel__heartbeat" in html
    assert "message-intel__loop" in html
    assert 'role="tablist"' in html
    assert 'href="/subnetsummer"' in core
    assert "Open full listener" in core
    assert 'data-pulse-pane="listen"' in html
    assert 'data-pulse-pane="learn"' in html
    assert 'data-pulse-pane="rank"' in html
    assert 'data-pulse-pane="serve"' in html
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
    assert "lsn-site" in html
    assert 'href="/"' in html
    assert "Open the full website" in html
    assert html.find("lsn-site") < html.find("lsn-hdr"), "full-site CTA must sit at the top of the listener, before the header"
    assert html.find("Open the full website") < html.find("Telegram pulse")
    assert ".lsn-site" in css
    assert "lsn-title" in html
    assert "lsn-bay" in html
    assert "lsn-loop" not in html
    assert 'role="tablist"' not in html
    assert "cosmic-sky" in html
    assert "council-first-theme" in html
    assert "Chatter Power" in html
    assert "/rank" in html
    assert "/who" in html
    assert "lsn-orbit" not in html
    assert "cosmic_resonance_core.html" in html
    assert "message-intel--listener-orbit" in html
    assert "COSMIC RESONANCE CORE" in open("templates/partials/premium/cosmic_resonance_core.html", encoding="utf-8").read()
    assert "lsn-hall" in html
    assert "lsn-rail" not in html
    assert "lsn-orbit-legend" not in html
    assert "closer = higher rank" in open("templates/partials/premium/cosmic_resonance_core.html", encoding="utf-8").read()
    assert "bigger = higher rank" in open("templates/partials/premium/cosmic_resonance_core.html", encoding="utf-8").read()
    assert ".lsn-orbit" in css
    assert ".lsn-hall" in css
    assert "@media (max-width: 520px)" in css
    assert ".lsn-tile--desk,.lsn-hall{grid-template-columns:1fr}" in css.replace(" ", "")
    page_rule = css.split(".lsn-page{", 1)[1].split("}", 1)[0].replace(" ", "")
    assert "max-width:430px" in page_rule, "full desk stays a phone column, even on a wide browser"
    assert "max-width:980px" not in css
    assert "1.2fr 1fr" not in css
    assert 'grid-template-areas:"orbit feed"' not in css
    assert 'data-anchor="true"' in html
    site_rule = css.split(".lsn-site{", 1)[1].split("}", 1)[0].replace(" ", "")
    assert "flex-wrap:wrap" in site_rule
    assert "lsn-zones" not in html
    assert "lsn-zone-feed" not in html
    assert "Telegram pulse" in html
    assert "Trending orbit" not in html or "TRENDING ORBIT" in html
    assert "message-intel-feed" in html
    assert "message-intel-conv-filters" in html
    assert "feed_rows(mi_messages)" in html
    assert "Syne" in html
    assert "Space+Grotesk" in html
    assert "wallet" not in html.lower()
    assert "lsn-vault" not in html
    assert ".lsn-intercept" in css
    assert "--lsn-font-brand:'Syne'" in css.replace(" ", "")
    resp = client.get("/subnetsummer")
    assert resp.status_code == 200
    body = resp.text
    assert "og-subnet-summer.png" in body
    assert "Subnet Summer Bot" in body
    assert "lsn-intercept" in body
    assert "COSMIC RESONANCE CORE" in body
    assert 'id="message-intel-sky"' in body
    assert "Open the full website" in body
    assert 'href="/"' in body
    assert body.find("Open the full website") < body.find("Telegram pulse")
    bounced = client.get("/listener", follow_redirects=False)
    assert bounced.status_code == 308
    assert bounced.headers.get("location") == "/subnetsummer"


def test_summers_divergence_mobile_and_keyboard_hooks():
    css = open("static/css/ui.css", encoding="utf-8").read()
    assert ".message-intel__divergence" in css
    assert ".message-intel__divergence-receipt:focus-visible" in css
    assert ".message-intel__divergence-head" in css
    assert ".message-intel__rank-header" in css
    assert ".message-intel__crowns-grid-v2" in css
    assert "minmax(0,1fr)" in css.replace(" ", "")
    listener_css = open("static/css/listener.css", encoding="utf-8").read()
    assert ".lsn-bay" in listener_css
    assert "overflow-x:clip" in listener_css.replace(" ", "")


def test_learn_proof_and_conviction_are_honest_when_empty():
    js = open("static/js/message_intel_feed.js", encoding="utf-8").read()
    assert "var defaultProof" not in js
    assert "var defaultHc" not in js
    assert "hit_rate: 60.9" not in js
    assert "var defaultCallers" not in js
    assert "No callers with enough graded calls yet" in js
    assert "No graded Telegram calls yet" in js
    assert "No ≥70% conviction messages yet" in js


def test_high_conviction_strip_default_is_seventy():
    import inspect
    from internal.message_intel.rollup import build_high_conviction_strip

    assert inspect.signature(build_high_conviction_strip).parameters["min_conviction"].default == 70.0
