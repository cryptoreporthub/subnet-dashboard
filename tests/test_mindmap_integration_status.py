"""Mindmap graph API — live integration_status field (PR M1)."""

from __future__ import annotations

import sys
from unittest.mock import patch

from fastapi.testclient import TestClient

from internal.learning.mindmap_aggregator import (
    _INTEGRATION_STATUS_VALUES,
    _judges_integration_status,
)
from server import app

_EXPECTED_INTEGRATION_KEYS = frozenset(
    {
        "council_trail",
        "expert_weights",
        "judges",
        "telegram_pulse",
        "dispositions",
        "pump_desk",
        "whales_indicators",
    }
)

def test_judges_integration_status_closed_when_weights_module_present():
    assert _judges_integration_status() == "closed"


def test_judges_integration_status_blocked_when_import_fails():
    with patch.dict(sys.modules, {"internal.judges.weights": None}):
        assert _judges_integration_status() == "blocked"


def test_mindmap_graph_integration_status():
    client = TestClient(app)
    resp = client.get("/api/mindmap/graph")
    assert resp.status_code == 200
    payload = resp.json()
    assert "integration_status" in payload
    status = payload["integration_status"]
    assert isinstance(status, dict)
    assert set(status.keys()) == _EXPECTED_INTEGRATION_KEYS
    for key, value in status.items():
        assert isinstance(value, str), f"{key} value must be str"
        assert value in _INTEGRATION_STATUS_VALUES, f"{key}={value!r} not in enum"
    # Lock the documented current values so a silent drift is caught.
    assert status["council_trail"] == "closed"
    assert status["expert_weights"] == "closed"
    assert status["judges"] == "closed"  # #720 per-judge weights wired into scoring
    assert status["telegram_pulse"] == "partial"
    assert status["dispositions"] == "display_only"
    assert status["pump_desk"] == "partial"
    assert status["whales_indicators"] == "read_only"
