import json
import os
import tempfile
import time

import pytest

from internal import freshness
from server import app


@pytest.fixture
def client():
    app.config["TESTING"] = True
    app.config["ENABLE_BACKGROUND_SYNC"] = False
    with app.test_client() as client:
        yield client


def test_freshness_endpoint(client):
    response = client.get("/api/freshness")
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data["status"] == "success"
    assert "data" in data
    assert "freshness" in data["data"]
    assert "registry" in data["data"]["freshness"]
    assert "soul_map" in data["data"]["freshness"]
    assert "recommendations" in data["data"]["freshness"]
    assert "watchlist" in data["data"]["freshness"]
    assert "overall" in data["data"]["freshness"]


def test_sync_endpoint(client):
    response = client.post("/api/sync")
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data["status"] == "success"
    assert "data" in data
    assert "registry" in data["data"]
    assert "freshness" in data["data"]


def test_registry_endpoint_includes_freshness(client):
    response = client.get("/api/registry")
    assert response.status_code == 200
    data = json.loads(response.data)
    # Backwards-compatible: subnet entries remain keyed by id; freshness is
    # attached as a sibling key (numeric ids never collide with "freshness").
    assert "freshness" in data
    subnet_keys = [k for k in data if k != "freshness"]
    assert subnet_keys, "expected at least one subnet entry"


def test_stats_endpoint_includes_freshness(client):
    response = client.get("/api/stats")
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data["status"] == "success"
    assert "freshness" in data
    assert "watchlist" in data["freshness"]


def test_source_freshness_detects_staleness():
    info = freshness.source_freshness(
        "/tmp/does-not-exist.json",
        threshold_seconds=1,
        embedded_updated_at="2000-01-01T00:00:00+00:00",
    )
    assert info["is_stale"] is True
    assert info["age_seconds"] is not None
    assert info["age_seconds"] > 0


def test_source_freshness_detects_freshness():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        f.write('{}')
        path = f.name
    try:
        info = freshness.source_freshness(path, threshold_seconds=3600)
        assert info["is_stale"] is False
    finally:
        os.unlink(path)


def test_merge_remote_registry_preserves_local_fields(tmp_path):
    registry = {
        "0": {
            "id": 0,
            "name": "Root",
            "status": "active",
            "last_updated": "2026-06-10T00:00:00+00:00",
            "emission": 3.0,
            "social_mentions": 2000,
            "is_overvalued": True,
            "description": "old",
        }
    }
    local_path = tmp_path / "registry.json"
    local_path.write_text(json.dumps(registry))

    remote = {
        "0": {
            "name": "Root",
            "description": "new",
            "owner": "owner-key",
        }
    }
    remote_path = tmp_path / "remote.json"
    remote_path.write_text(json.dumps(remote))

    result = freshness.merge_remote_registry(
        registry_path=str(local_path), remote_url=f"file://{remote_path}"
    )
    assert result["ok"] is True
    merged = json.loads(local_path.read_text())
    assert merged["0"]["description"] == "new"
    assert merged["0"]["owner"] == "owner-key"
    assert merged["0"]["emission"] == 3.0
    assert merged["0"]["social_mentions"] == 2000


def test_watchlist_freshness_detects_staleness():
    info = freshness.watchlist_freshness("/tmp/does-not-exist-watchlist.json")
    assert info["is_stale"] is True
    assert info["age_seconds"] is None
    assert info["last_updated"] is None


def test_watchlist_refresh_updates_timestamps(tmp_path):
    watchlist = {
        "protocols": {
            "HYPE": {
                "symbol": "HYPE",
                "name": "Hyperliquid",
                "category": "DeFi / Perpetuals",
                "price": 18.75,
                "change_24h": 0.089,
                "mentions": 2100,
                "tags": ["defi", "perps", "l1"],
                "url": "https://hyperliquid.xyz",
                "description": "High-performance L1 for perpetuals.",
            }
        }
    }
    local_path = tmp_path / "watchlist.json"
    local_path.write_text(json.dumps(watchlist))

    result = freshness.refresh_watchlist(str(local_path))
    assert result["ok"] is True
    assert result["protocol_count"] == 1

    merged = json.loads(local_path.read_text())
    assert "last_updated" in merged
    assert "last_updated" in merged["protocols"]["HYPE"]


def test_sync_endpoint_includes_watchlist(client):
    response = client.post("/api/sync")
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data["status"] == "success"
    assert "watchlist" in data["data"]
    assert data["data"]["watchlist"]["ok"] is True
