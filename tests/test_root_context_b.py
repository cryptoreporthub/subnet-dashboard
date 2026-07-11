"""Tests for Agent B root-page context (slice 12b)."""

from internal.analytics.root_context import build_agent_b_root_context


def test_build_agent_b_root_context_keys():
    ctx = build_agent_b_root_context(subnets=[], data_source="registry")
    for key in (
        "pump_analytics",
        "pump_summary",
        "scenario_summary",
        "api_indicators_convergence",
        "indicator_state",
        "whale_intelligence",
        "ruggers_watchlist",
        "oracle_snapshot",
        "price_tracking_baselines",
    ):
        assert key in ctx


def test_summaries_are_non_empty_strings():
    ctx = build_agent_b_root_context(subnets=[], data_source="registry")
    assert isinstance(ctx["pump_summary"], str) and len(ctx["pump_summary"]) > 10
    assert isinstance(ctx["scenario_summary"], str) and len(ctx["scenario_summary"]) > 10


def test_root_get_includes_agent_b_context():
    from fastapi.testclient import TestClient

    from server import app

    with TestClient(app) as client:
        response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")
