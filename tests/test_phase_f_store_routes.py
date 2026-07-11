"""Phase F — guarded /api/store/* read routes (Agent B)."""

from __future__ import annotations

import sys
from types import ModuleType
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from server import app


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def fake_store():
    mod = ModuleType("internal.store")
    mod.get_trail_rows = lambda limit=100, signal=None: [
        {"event_type": "signal_triggered", "signal": signal or "pick", "time": "2026-07-11T00:00:00Z"}
    ][:limit]
    mod.get_dispositions = lambda: [
        {"subnet_id": "1", "recommended_action": "accumulate"},
        {"subnet_id": "2", "recommended_action": "hold"},
    ]
    mod.get_decision_lineage = lambda limit=100: [
        {"id": "trace-1", "decision_type": "pick", "subnet": "Alpha"},
    ][:limit]
    mod.get_store_stats = lambda: {
        "trail_count": 53,
        "disposition_count": 24,
        "decision_lineage_count": 12,
        "backend": "sqlite",
    }
    return mod


def test_store_trail_endpoint(client, fake_store):
    with patch.dict(sys.modules, {"internal.store": fake_store}):
        resp = client.get("/api/store/trail?limit=5&signal=pick")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "success"
    assert body["count"] == 1
    assert isinstance(body["rows"], list)


def test_store_dispositions_endpoint(client, fake_store):
    with patch.dict(sys.modules, {"internal.store": fake_store}):
        resp = client.get("/api/store/dispositions")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "success"
    assert body["count"] == 2
    assert isinstance(body["dispositions"], list)


def test_store_decision_lineage_endpoint(client, fake_store):
    with patch.dict(sys.modules, {"internal.store": fake_store}):
        resp = client.get("/api/store/decision-lineage?limit=10")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "success"
    assert body["count"] == 1
    assert isinstance(body["records"], list)


def test_store_stats_endpoint(client, fake_store):
    with patch.dict(sys.modules, {"internal.store": fake_store}):
        resp = client.get("/api/store/stats")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "success"
    assert body["stats"]["trail_count"] == 53
    assert body["stats"]["backend"] == "sqlite"


@pytest.mark.parametrize(
    "path",
    [
        "/api/store/trail",
        "/api/store/dispositions",
        "/api/store/decision-lineage",
        "/api/store/stats",
    ],
)
def test_store_endpoints_unavailable_when_module_missing(client, path):
    with patch.dict(sys.modules, {"internal.store": None}):
        resp = client.get(path)
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "unavailable"
    assert "detail" in body
