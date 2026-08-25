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
