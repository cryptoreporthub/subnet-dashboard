"""Phase LB — integrations strip SSR on homepage."""

from __future__ import annotations

from types import SimpleNamespace

from server import _integrations_strip_ssr, templates


def test_integrations_strip_ssr_context():
    ctx = _integrations_strip_ssr()
    strip = ctx["integrations_strip"]
    assert strip["integration_total"] == 6
    assert len(strip["integrations"]) == 6
    assert all(row["status"] == "checking" for row in strip["integrations"])
    slugs = {row["slug"] for row in strip["integrations"]}
    assert "chutes" in slugs


def test_pulse_strip_template_renders_ssr_skeleton():
    tpl = templates.env.get_template("partials/premium/pulse_strip.html")
    html = tpl.render(
        mi_breadth="bullish",
        mi_total=128,
        mi_ns=SimpleNamespace(gainers=70, losers=58),
        mi_avg_chg=1.25,
        sig_list=[1, 2, 3],
        alert_list=[1],
        **_integrations_strip_ssr(),
    )
    assert "sr-pulse-ribbon" in html
    assert "sr-pulse__oneline" in html
    assert "subnet-int-strip--ssr" in html
    assert "Finney (mainnet)" in html
    assert "Chutes (SN64)" in html
    assert "Built on Bittensor" in html
    assert 'id="subnetIntegrationsBar"' in html
