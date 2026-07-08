"""Tests for the TaoStats API client with mocked HTTP responses."""

import json
import urllib.request
from unittest.mock import Mock, patch

import pytest

from internal.indicators.taostats_client import (
    get_dtao_pool_latest,
    get_subnet_delegation_flow,
    get_subnet_registration_cost,
    get_tao_price,
    get_tao_price_history,
)


@pytest.fixture(autouse=True)
def _setup_env(monkeypatch):
    """Ensure TAOSTATS_API_KEY is set for every test.

    Must also patch the module-level constant since it's read at import time
    before any test fixtures run.
    """
    monkeypatch.setenv("TAOSTATS_API_KEY", "test-key-12345")
    monkeypatch.setattr("internal.indicators.taostats_client.TAOSTATS_API_KEY", "test-key-12345")


def _build_response(data, status=200):
    """Build a file-like object mimicking urllib.response.addinfourl."""
    payload = json.dumps(data).encode()

    class FakeResponse:
        def __init__(self):
            self.status = status

        def read(self):
            return payload

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    return FakeResponse()


def test_get_dtao_pool_latest_success(monkeypatch):
    data = {"data": {"price": 1.25, "liquidity": 500_000, "conviction": 0.8}}
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, **kw: _build_response(data))

    result = get_dtao_pool_latest(netuid=18)
    assert result == data


def test_get_dtao_pool_latest_no_api_key(monkeypatch):
    monkeypatch.delenv("TAOSTATS_API_KEY", raising=False)
    monkeypatch.setattr("internal.indicators.taostats_client.TAOSTATS_API_KEY", "")
    result = get_dtao_pool_latest(netuid=1)
    assert result is None


def test_get_subnet_delegation_flow_success(monkeypatch):
    data = {"data": [{"amount": 1000, "direction": "stake"}]}
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, **kw: _build_response(data))

    result = get_subnet_delegation_flow(netuid=18)
    assert result == data


def test_get_subnet_registration_cost_success(monkeypatch):
    data = {"data": {"cost": 5.5}}
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, **kw: _build_response(data))

    result = get_subnet_registration_cost(netuid=18)
    assert result == data


def test_get_tao_price_success(monkeypatch):
    data = {"data": {"price": 420.0}}
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, **kw: _build_response(data))

    result = get_tao_price()
    assert result == data


def test_get_tao_price_history_success(monkeypatch):
    data = {"data": [{"timestamp": "2024-01-01", "price": 400.0}]}
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, **kw: _build_response(data))

    result = get_tao_price_history()
    assert result == data


def test_api_timeout_logs_error(monkeypatch, caplog):
    import logging

    caplog.set_level(logging.ERROR)

    def _failing(**_):
        raise Exception("timeout")

    monkeypatch.setattr(urllib.request, "urlopen", _failing)

    result = get_tao_price()
    assert result is None
    assert "TaoStats API error" in caplog.text