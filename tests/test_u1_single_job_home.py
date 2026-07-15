"""§17.U1 — single-job home hero."""

from __future__ import annotations

from fastapi.testclient import TestClient

from internal.analytics.root_context import build_agent_b_root_context
from server import app


def test_root_context_u1_keys():
    ctx = build_agent_b_root_context(subnets=[], data_source="registry", pick_netuid=1)
    assert "conviction_band" in ctx
    assert "daily_pick_stage" in ctx
    assert ctx["conviction_band"]["band"] is None or ctx["conviction_band"]["band"] in (
        "high",
        "medium",
        "low",
    )


def test_index_u1_single_job_home():
    with TestClient(app) as client:
        html = client.get("/").text
    assert 'class="council-stage home-job"' in html or "home-job" in html
    assert "home-job__why" in html
    assert "home-job__cta" in html
    assert "home-band" in html or "home-band--empty" in html
    assert "home-enrichment" in html
    assert 'id="pro-cockpit"' in html
    # Hero before Pro + market drawers
    assert html.index("home-job") < html.index('id="pro-cockpit"')
    assert html.index('id="pro-cockpit"') < html.index('id="market-drawer"')


def test_index_canonical_meta():
    with TestClient(app) as client:
        html = client.get("/").text
    assert 'rel="canonical"' in html
    assert 'property="og:url"' in html
