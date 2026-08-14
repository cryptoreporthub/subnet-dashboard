"""Phase L slice 1 — signal pipeline and persistence."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from internal.signals.pipeline import build_signal, generate_signals
from internal.signals import routes
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
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
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


def test_api_signals_refreshes_empty_cache_once(client, tmp_path, monkeypatch):
    """The homepage's refresh=false read repairs an empty signal cache."""
    path = str(tmp_path / "empty-signals.json")
    monkeypatch.setattr(routes, "_store", SignalStore(path=path))
    generated = [
        {
            "subnet_id": 7,
            "name": "Alpha",
            "signal_type": "buy",
            "confidence": 0.8,
            "source_expert": "quant",
            "timestamp": "2099-01-01T00:00:00Z",
            "evidence": "test",
        }
    ]
    calls = []

    def fake_generate(persist=True):
        calls.append(persist)
        routes._get_store().append_many(generated)
        routes._get_store().mark_refreshed("2099-01-01T00:00:00Z")
        return {
            "signals": generated,
            "changed_signals": generated,
            "meta": {"count": 1, "appended": 1},
        }

    monkeypatch.setattr(routes, "generate_signals", fake_generate)

    first = client.get("/api/signals?refresh=false")
    second = client.get("/api/signals?refresh=false")

    assert first.status_code == 200
    assert first.json()["signals"][0]["subnet_id"] == 7
    assert first.json()["signals"][0]["confidence"] == 0.8
    assert first.json()["meta"].get("cached") is not True
    assert second.json()["signals"][0]["subnet_id"] == 7
    assert second.json()["signals"][0]["confidence"] == 0.8
    assert len(calls) == 1


def test_signal_refresh_is_single_flight(tmp_path, monkeypatch):
    """Concurrent stale reads share one generator invocation."""
    import asyncio
    import time

    path = str(tmp_path / "single-flight-signals.json")
    monkeypatch.setattr(routes, "_store", SignalStore(path=path))
    generated = [
        {
            "subnet_id": 8,
            "name": "Beta",
            "signal_type": "neutral",
            "confidence": 0.5,
            "source_expert": "technical",
            "timestamp": "2099-01-01T00:00:00Z",
            "evidence": "test",
        }
    ]
    calls = []

    class FakeAlerts:
        def check_system_alerts(self):
            return []

        def record_signal_changes(self, _signals):
            return []

        def evaluate_correlation_alerts(self, _signals):
            return []

    def fake_generate(persist=True):
        calls.append(persist)
        time.sleep(0.05)
        routes._get_store().append_many(generated)
        routes._get_store().mark_refreshed("2099-01-01T00:00:00Z")
        return {"signals": generated, "changed_signals": generated}

    monkeypatch.setattr(routes, "generate_signals", fake_generate)
    monkeypatch.setattr(routes, "_get_alerts", lambda: FakeAlerts())

    async def run():
        return await asyncio.gather(
            routes._refresh_and_broadcast(only_if_stale=True),
            routes._refresh_and_broadcast(only_if_stale=True),
        )

    results = asyncio.run(run())

    assert len(calls) == 1
    assert all(result["signals"] for result in results)


def test_store_freshness_uses_full_refresh_not_row_change_time(tmp_path):
    store = SignalStore(path=str(tmp_path / "refresh-time.json"))
    store.append_many(
        [
            {
                "subnet_id": 1,
                "signal_type": "buy",
                "confidence": 0.7,
                "timestamp": "2020-01-01T00:00:00Z",
            },
            {
                "subnet_id": 2,
                "signal_type": "neutral",
                "confidence": 0.5,
                "timestamp": "2024-01-01T00:00:00Z",
            },
        ]
    )
    store.mark_refreshed("2099-01-01T00:00:00Z")

    assert routes._store_is_fresh(store) is True

    store.mark_refreshed("2020-01-01T00:00:00Z")
    assert routes._store_is_fresh(store) is False


def test_automatic_refresh_timeout_keeps_stale_cache(monkeypatch):
    """A slow generator never blanks the homepage's existing signal data."""
    import asyncio

    stale = [{"subnet_id": 9, "timestamp": "2020-01-01T00:00:00Z"}]

    async def timed_out(*args, **kwargs):
        raise asyncio.TimeoutError

    monkeypatch.setattr(routes, "_to_thread_timeout", timed_out)

    result = asyncio.run(
        routes._refresh_and_broadcast(
            only_if_stale=True,
            fallback_signals=stale,
        )
    )

    assert result["signals"] == stale
    assert result["meta"]["stale"] is True
    assert result["meta"]["source"] == "timeout"
