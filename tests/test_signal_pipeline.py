"""Phase L slice 1 — signal pipeline and persistence."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from internal.signals.pipeline import build_signal, generate_signals
from internal.signals.store import SignalStore
from server import app


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def temp_store(tmp_path, monkeypatch):
    path = str(tmp_path / "signals.json")
    monkeypatch.setenv("SIGNALS_PATH", path)
    return SignalStore(path=path)


def test_store_append_ttl_and_index(temp_store):
    store = temp_store
    row = {
        "subnet_id": 3,
        "signal_type": "buy",
        "confidence": 0.7,
        "source_expert": "hype",
        "timestamp": "2026-07-12T10:00:00Z",
        "evidence": "test",
    }
    assert len(store.append_many([row])) == 1
    assert len(store.append_many([row])) == 0  # unchanged dedupe
    assert store.query(subnet_id=3)[0]["subnet_id"] == 3
    summary = store.summary()["summary"]
    assert summary["buy_count"] == 1
    assert summary["total_signals"] == 1


def test_build_signal_shape():
    sn = {
        "netuid": 1,
        "name": "Alpha",
        "price": 12.0,
        "volume": 50000,
        "price_change_24h": 3.0,
        "emission": 2.0,
        "apy": 25.0,
    }
    row = build_signal(sn, {"tao_change_24h": 0.0, "weights": {}})
    assert row["signal_type"] in ("buy", "sell", "neutral")
    assert row["source_expert"] in ("quant", "hype", "dark_horse", "technical")
    assert 0.0 <= row["confidence"] <= 1.0
    assert row["evidence"]


def test_api_signals_and_summary(client):
    resp = client.get("/api/signals")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "success"
    assert len(body["signals"]) >= 100
    assert all(s.get("subnet_id") is not None for s in body["signals"])

    summary = client.get("/api/signals/summary")
    assert summary.status_code == 200
    s = summary.json()["summary"]
    assert "buy_sell_ratio" in s
    assert "avg_confidence" in s
    assert "total_signals" in s
