"""§17.S3 — whale enrichment badge."""

from __future__ import annotations

import json

import pytest

from internal.whales.enrichment_badge import (
    empty_whale_flow_badge,
    whale_flow_badge,
    whale_flow_badge_from_flow,
)
from internal.whales.service import WhaleIntelligenceService


def test_empty_badge_shape():
    badge = empty_whale_flow_badge("no_pick")
    assert badge["kind"] == "whale_flow"
    assert badge["status"] == "empty"
    assert badge["reason"] == "no_pick"
    assert "label" in badge


def test_badge_empty_when_ledger_has_no_events():
    flow = {
        "netuid": 1,
        "data_available": False,
        "reason": "no_events",
        "open_positions": 0,
    }
    badge = whale_flow_badge_from_flow(flow)
    assert badge["status"] == "empty"
    assert badge["reason"] == "no_events"


def test_badge_live_smart_money():
    flow = {
        "netuid": 7,
        "data_available": True,
        "open_positions": +2,
        "smart_money_present": True,
        "avoid_follow": False,
    }
    badge = whale_flow_badge_from_flow(flow)
    assert badge["status"] == "live"
    assert badge["label"] == "Smart money in"


def test_badge_live_rugger_activity():
    flow = {
        "netuid": 3,
        "data_available": True,
        "open_positions": 1,
        "smart_money_present": False,
        "avoid_follow": True,
    }
    badge = whale_flow_badge_from_flow(flow)
    assert badge["status"] == "live"
    assert badge["label"] == "Rugger activity"


def test_badge_flow_flip_accumulation():
    flow = {
        "netuid": 64,
        "data_available": True,
        "open_positions": 1,
        "smart_money_present": False,
        "avoid_follow": False,
        "flow_flip": {"flip_direction": "accumulation", "kind": "flow_flip"},
    }
    badge = whale_flow_badge_from_flow(flow)
    assert badge["status"] == "live"
    assert badge["label"] == "Flow flip · accumulation"
    assert badge.get("flow_flip") is True


def test_whale_flow_badge_with_service(tmp_path):
    data = tmp_path / "intel.json"
    data.write_text(
        json.dumps(
            {
                "events": [{"wallet": "w", "netuid": 5, "side": "buy", "amount_tao": 10}],
                "open_positions": {},
                "profiles": {},
                "closed_trades": [],
            }
        ),
        encoding="utf-8",
    )
    svc = WhaleIntelligenceService(data_path=str(data))
    badge = whale_flow_badge(5, service=svc)
    assert badge["status"] == "empty"
    assert badge["reason"] == "no_positions"


def test_api_daily_pick_includes_enrichment_badge():
    from fastapi.testclient import TestClient

    from server import app

    with TestClient(app) as client:
        body = client.get("/api/daily-pick").json()
    assert "enrichment_badge" in body
    badge = body["enrichment_badge"]
    assert badge["kind"] == "whale_flow"
    assert badge["status"] in ("live", "empty")


def test_root_context_includes_enrichment_badge():
    from internal.analytics.root_context import build_agent_b_root_context

    ctx = build_agent_b_root_context(subnets=[], data_source="registry", pick_netuid=1)
    assert "enrichment_badge" in ctx
    assert ctx["enrichment_badge"]["status"] in ("live", "empty")
