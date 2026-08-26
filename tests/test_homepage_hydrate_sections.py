"""Homepage hydrate targets: market drawer restored, hour watch, SSR-only patches."""

from pathlib import Path

from fastapi.testclient import TestClient

from server import app

COCKPIT = Path("templates/partials/premium_cockpit.html")
HYDRATE = Path("static/js/cockpit_hydrate.js")

MARKET_PARTIALS = (
    "partials/premium/hero.html",
    "partials/premium/scanner.html",
    "partials/premium/investigation.html",
    "partials/premium/signals.html",
    "partials/premium/alerts.html",
    "partials/premium/staking.html",
    "partials/premium/indicators.html",
    "partials/premium/undervalued.html",
    "partials/premium/radar.html",
    "partials/premium/subnet_groups.html",
    "partials/premium/social.html",
    "partials/premium/chat.html",
    "partials/premium/footer.html",
)

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
    "section-footer",
]


def test_market_drawer_not_truncated():
    html = COCKPIT.read_text(encoding="utf-8")
    assert "read_links truncated" not in html
    assert 'id="market-drawer"' in html
    assert "</details>" in html.split('id="market-drawer"', 1)[1]
    for partial in MARKET_PARTIALS:
        assert f'include "{partial}"' in html, partial


def test_hydrate_patches_ssr_only_ribs():
    js = HYDRATE.read_text(encoding="utf-8")
    for name in (
        "function patchMarketPulse",
        "function patchTodaysIntel",
        "function patchSimileads",
        "function patchDevSignalsDesk",
        "patchMarketPulse(subnets)",
        "patchSimileads(top, lastSubnets)",
        "patchDevSignalsDesk(signals)",
    ):
        assert name in js, name


def test_index_has_h_full_section_ids_and_hour_watch():
    import server as srv

    srv._prime_emergency_home_html()
    srv._warm_homepage_cache(None)
    with TestClient(app) as client:
        html = client.get("/").text
    assert "read_links truncated" not in html
    for section_id in H_FULL_SECTION_IDS:
        assert f'id="{section_id}"' in html, section_id
    assert 'id="hour-watch-now"' in html
    assert 'id="hour-watch-shift"' in html
    assert 'id="chatLog"' in html
    assert 'id="cpol-netflow"' in html
    assert 'id="market-pulse-breadth"' in html


def test_priority_panels_self_hydrate_even_when_cockpit_owns_flag():
    brain = Path("static/js/brain_letter.js").read_text(encoding="utf-8")
    drivers = Path("static/js/market_drivers_ui.js").read_text(encoding="utf-8")
    hydrate = HYDRATE.read_text(encoding="utf-8")
    assert 'dataset.hydrate !== "1"' not in brain
    assert 'dataset.hydrate !== "1"' not in drivers
    assert "return gradedCountFromDom() > 0" not in brain
    assert "function kickPriorityPanels" in hydrate
    assert "kickPriorityPanels()" in hydrate


def test_homepage_hydrate_no_all_ones_on_weights_error():
    from fastapi.testclient import TestClient

    from server import app

    with TestClient(app) as client:
        resp = client.get("/api/council/weights")
    data = resp.json()
    if data.get("status") == "degraded":
        assert data.get("data") is None
        assert data.get("weights_degraded") is True
        assert "error" in data
    else:
        assert data.get("status") in {"success", "ok"}


def test_dev_pulse_error_empty_split():
    js = Path("static/js/dev_pulse.js").read_text(encoding="utf-8")
    assert "Could not load Dev Pulse — try again shortly." in js
    assert "payload.empty" in js
    assert "is-error" in js


def test_judges_eager_not_idle_deferred():
    deferred = Path("static/js/home_deferred.js").read_text(encoding="utf-8")
    scripts = Path("templates/partials/premium/scripts.html").read_text(encoding="utf-8")
    assert "premium_judges.js" not in deferred
    assert "premium_judges.js" in scripts
    assert "premium_scanner.js" in deferred
