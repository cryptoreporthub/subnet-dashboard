"""Tests for on-chain investigation service."""

from unittest.mock import patch

from internal.investigation.service import (
    investigate_subnet_sellers,
    trace_wallet_flow,
)


def test_subnet_sellers_unavailable_without_key(monkeypatch):
    monkeypatch.setenv("TAOSTATS_API_KEY", "")
    import fetchers.taostats_client as ts

    monkeypatch.setattr(ts, "TAOSTATS_API_KEY", "")
    result = investigate_subnet_sellers(82)
    assert result["status"] == "unavailable"


def test_trace_wallet_flow_structure():
    wallet_data = {
        "status": "success",
        "wallet": "5A",
        "transfers_out": [{"to": "5B", "amount": 1}],
        "delegation_events": [{"is_transfer": True, "transfer_address": "5B"}],
        "sells": [],
        "buys": [],
        "sell_total_tao": 0,
        "buy_total_tao": 0,
    }
    with patch("internal.investigation.service._investigate_wallet", return_value=wallet_data):
        result = trace_wallet_flow("5A", counterparty="5B", limit=10)
    assert result["status"] == "success"
    assert result["counterparty"] == "5B"
    assert len(result["transfer_links"]) == 1


def test_chat_investigation_tools_registry():
    from internal.simivision import chat_service

    tools = chat_service._register_investigation_tools()
    assert "get_subnet_sellers" in tools
    assert "get_wallet_activity" in tools
    assert "trace_transfers" in tools
    assert "get_subnet_owner" in tools

    chat_service.INVESTIGATION_TOOLS = {
        "get_subnet_sellers": lambda netuid, days=7: {"status": "success", "netuid": netuid},
    }
    out = chat_service.invoke_investigation_tool("get_subnet_sellers", netuid=82)
    assert out.get("status") == "success"
    assert out.get("netuid") == 82
