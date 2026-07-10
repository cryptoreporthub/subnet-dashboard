"""Tests for Agent B root-page context (slice 12b)."""

from internal.analytics.root_context import build_agent_b_root_context


def test_build_agent_b_root_context_keys():
    ctx = build_agent_b_root_context(subnets=[], data_source="registry")
    for key in (
        "pump_analytics",
        "api_indicators_convergence",
        "indicator_state",
        "whale_intelligence",
        "ruggers_watchlist",
        "oracle_snapshot",
        "price_tracking_baselines",
    ):
        assert key in ctx


def test_root_get_includes_agent_b_context():
    from fastapi.testclient import TestClient

    from server import app

    with TestClient(app) as client:
        response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")
