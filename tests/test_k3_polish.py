"""K3-5 polish: onboarding trim, SN118 chip, alert dot wiring."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from server import app


def test_k3_5_footer_sn118_chip():
    with TestClient(app) as client:
        html = client.get("/").text
    assert "subnetIntegrationsBar" in html
    assert "subnet_integrations.js" in html
    assert "Built on Bittensor" in html


def test_k3_5_onboarding_three_steps():
    body = Path("static/js/onboarding_tour.js").read_text(encoding="utf-8")
    assert "#market-drawer" not in body
    assert body.count("element:") == 3


def test_k3_5_backtest_methodology_open_by_default():
    body = Path("static/js/cockpit_hydrate.js").read_text(encoding="utf-8")
    assert 'class="backtest-method card" open' in body


def test_k3_5_alert_dot_hook():
    body = Path("static/js/watchlist_alerts.js").read_text(encoding="utf-8")
    assert "habit-alert-btn--dot" in body
    assert "/api/conviction-alerts/status" in body


def test_hydrate_registry_name_resolution():
    hydrate = Path("static/js/cockpit_hydrate.js").read_text(encoding="utf-8")
    living = Path("static/js/living_focus.js").read_text(encoding="utf-8")
    assert "SubnetNameRegistry" in hydrate
    assert "indexRegistry" in hydrate
    assert "isBadSubnetName" in hydrate
    assert "SubnetNameRegistry.resolve" in living


def test_weighed_hydrate_runs_even_when_daily_pick_fails():
    hydrate = Path("static/js/cockpit_hydrate.js").read_text(encoding="utf-8")
    assert "function hydrateWeighedAlternatives" in hydrate
    tier = hydrate.split("// Tier 1a — daily call first", 1)[1].split("// Tier 1b", 1)[0]
    assert "hydrateWeighedAlternatives(dpResult" in tier
    assert tier.index("hydrateWeighedAlternatives") > tier.index("catch (e)")
