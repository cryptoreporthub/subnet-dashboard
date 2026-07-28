"""SS-TG W5 — feed filters (min conviction + subnet, sessionStorage client)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from server import app


@pytest.fixture
def intel_env(tmp_path, monkeypatch):
    db_path = str(tmp_path / "message_intel.db")
    monkeypatch.setenv("MESSAGE_INTEL_DB", db_path)
    from internal.message_intel import store

    store.reset_db_cache()
    yield store.get_db(db_path)


@pytest.fixture
def client(intel_env):
    with TestClient(app) as c:
        yield c


def _seed_message(
    db,
    *,
    content: str,
    conviction: float = 72.0,
    netuid: int = 25,
):
    mid, _ = db.save_message(
        {
            "source": "telegram",
            "group_name": "OfficialSubnetSummer",
            "author_name": "Nick",
            "content": content,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    )
    db.save_analysis(
        mid,
        {
            "sentiment": "bullish",
            "entities": {"subnets": [f"SN{netuid}"]},
            "influence_score": 0.5,
        },
    )
    db.save_verdict(
        mid,
        {
            "verdict": "bullish",
            "conviction": conviction,
            "reasoning": "Subnet mention.",
            "predicted_direction": "up",
        },
    )
    db.save_price_snapshot(mid, 1.25, netuid=netuid)
    return mid


def test_list_without_filters_unchanged(client, intel_env):
    _seed_message(intel_env, content="SN25 low", conviction=55.0, netuid=25)
    _seed_message(intel_env, content="SN18 high", conviction=82.0, netuid=18)
    payload = client.get("/api/message-intel?limit=10").json()
    assert payload["status"] == "success"
    assert payload["count"] == 2
    assert payload.get("filtered_empty") is False
    assert "filters" not in (payload.get("meta") or {})


def test_min_conviction_filter(client, intel_env):
    _seed_message(intel_env, content="SN25 low", conviction=55.0, netuid=25)
    _seed_message(intel_env, content="SN18 high", conviction=82.0, netuid=18)
    payload = client.get("/api/message-intel?limit=10&min_conviction=70").json()
    assert payload["status"] == "success"
    assert payload["count"] == 1
    assert payload["messages"][0]["verdict"]["conviction"] >= 70
    assert payload["meta"]["filters"]["min_conviction"] == 70


def test_netuid_filter(client, intel_env):
    _seed_message(intel_env, content="SN25 low", conviction=55.0, netuid=25)
    _seed_message(intel_env, content="SN18 high", conviction=82.0, netuid=18)
    payload = client.get("/api/message-intel?limit=10&netuid=18").json()
    assert payload["status"] == "success"
    assert payload["count"] == 1
    assert payload["messages"][0]["netuid"] == 18
    assert payload["meta"]["filters"]["netuid"] == 18


def test_combined_filters_and_filtered_empty(client, intel_env):
    _seed_message(intel_env, content="SN25 low", conviction=55.0, netuid=25)
    _seed_message(intel_env, content="SN18 high", conviction=82.0, netuid=18)
    payload = client.get("/api/message-intel?limit=10&min_conviction=90&netuid=18").json()
    assert payload["status"] == "success"
    assert payload["count"] == 0
    assert payload["empty"] is True
    assert payload["filtered_empty"] is True


def test_list_route_accepts_same_filters(client, intel_env):
    _seed_message(intel_env, content="SN25 low", conviction=55.0, netuid=25)
    _seed_message(intel_env, content="SN18 high", conviction=82.0, netuid=18)
    payload = client.get("/api/message-intel/list?limit=10&min_conviction=80").json()
    assert payload["status"] == "success"
    assert payload["count"] == 1


def test_w5_template_and_client_markers():
    html = open("templates/partials/premium/message_intel_feed.html", encoding="utf-8").read()
    js = open("static/js/message_intel_feed.js", encoding="utf-8").read()
    css = open("static/css/council_first.css", encoding="utf-8").read()
    assert "message-intel-filter-bar" in html
    assert "message-intel-conv-filters" in html
    assert "message-intel-subnet-filters" in html
    assert "message-intel-filters" in js
    assert "renderFilterEmpty" in js
    assert "buildListUrl" in js
    assert "message-intel__filter-bar" in css
    assert "message-intel__filter-chip--active" in css
