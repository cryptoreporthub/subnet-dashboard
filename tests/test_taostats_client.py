"""Tests for the TaoStats API client with mocked HTTP responses."""

import json
from unittest.mock import patch

import pytest

from fetchers import taostats_client as ts


@pytest.fixture(autouse=True)
def _setup_env(monkeypatch):
    monkeypatch.setenv("TAOSTATS_API_KEY", "test-key-12345")
    monkeypatch.setattr(ts, "TAOSTATS_API_KEY", "test-key-12345")


def _mock_response(data, status=200):
    class Resp:
        status_code = status

        @staticmethod
        def json():
            return data

    return Resp()


def test_get_subnet_delegation_flow_success():
    payload = {"data": [{"nominator": "5abc", "action": "undelegate", "amount": 10}]}
    with patch.object(ts, "requests") as mock_req:
        mock_req.get.return_value = _mock_response(payload)
        result = ts.get_subnet_delegation_flow(netuid=18)
    assert result == payload
    url = mock_req.get.call_args.args[0]
    assert "/api/v1/subnets/18/delegations" in url


def test_get_delegation_events_uses_api_not_apiv1_prefix():
    payload = {"data": [{"nominator": {"ss58": "5abc"}, "action": "DELEGATE", "amount": "1750000000"}]}
    with patch.object(ts, "requests") as mock_req:
        mock_req.get.return_value = _mock_response(payload)
        result = ts.get_delegation_events(netuid=108, limit=10)
    assert result == payload
    url = mock_req.get.call_args.args[0]
    assert url.endswith("/api/delegation/v1")
    assert "/api/v1/delegation" not in url
    params = mock_req.get.call_args.kwargs.get("params") or {}
    assert params.get("order") == "timestamp_desc"
    assert params.get("netuid") == 108


def test_get_subnet_identity_skips_without_key(monkeypatch):
    monkeypatch.setattr(ts, "TAOSTATS_API_KEY", "")
    assert ts.get_subnet_identity(1) is None


def test_is_available():
    assert ts.is_available() is True
