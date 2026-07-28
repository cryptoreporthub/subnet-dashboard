"""SS-TG W4 — 24h summary strip rollup + API + template markers."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

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


def _seed_message(db, *, netuid: int = 25, conviction: float = 72.0, hours_ago: float = 1.0):
    ts = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    mid, _ = db.save_message(
        {
            "source": "telegram",
            "group_name": "OfficialSubnetSummer",
            "author_name": "Nick",
            "content": f"SN{netuid} is heating up",
            "timestamp": ts.isoformat(),
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
            "reasoning": "Strong subnet mention.",
            "predicted_direction": "up",
        },
    )
    db.save_price_snapshot(mid, 1.25, netuid=netuid)
    return mid


def test_build_24h_summary_honest_empty(intel_env):
    from internal.message_intel.rollup import build_24h_summary

    for i in range(3):
        _seed_message(intel_env, netuid=25 + i, hours_ago=0.5 + i * 0.1)

    summary = build_24h_summary(db=intel_env)
    assert summary["ready"] is False
    assert summary["message_count"] == 3
    assert "empty_reason" in summary
    assert "top_subnets" not in summary


def test_build_24h_summary_ready_with_rollups(intel_env):
    from internal.message_intel.rollup import build_24h_summary

    for i in range(12):
        _seed_message(
            intel_env,
            netuid=25 if i < 8 else 12,
            conviction=65.0 if i % 2 == 0 else 40.0,
            hours_ago=0.2 + i * 0.05,
        )
    for i in range(4):
        _seed_message(intel_env, netuid=25, conviction=50.0, hours_ago=30 + i)

    summary = build_24h_summary(db=intel_env, registry_names={25: "TaoHash", 12: "Apex"})
    assert summary["ready"] is True
    assert summary["message_count"] == 12
    assert summary["high_conviction_count"] == 6
    assert summary["top_subnets"][0]["netuid"] == 25
    assert summary["top_subnets"][0]["name"] == "TaoHash"
    assert summary["group_pulse"]["messages"] == 12
    assert summary["group_pulse"]["high_conviction"] == 6
    assert summary["movers"]
    assert summary["movers"][0]["change"] >= 0


def test_list_meta_includes_summary_24h(client, intel_env):
    for i in range(10):
        _seed_message(intel_env, netuid=25, conviction=70.0, hours_ago=0.1 + i * 0.05)

    payload = client.get("/api/message-intel?limit=5").json()
    assert payload["status"] == "success"
    summary = payload["meta"].get("summary_24h") or {}
    assert summary.get("ready") is True
    assert summary.get("message_count") == 10
    assert isinstance(summary.get("top_subnets"), list)
    assert isinstance(summary.get("movers"), list)
    assert "group_pulse" in summary


def test_summers_template_has_w4_markers():
    html = open("templates/partials/premium/message_intel_feed.html", encoding="utf-8").read()
    js = open("static/js/message_intel_feed.js", encoding="utf-8").read()
    css = open("static/css/council_first.css", encoding="utf-8").read()
    assert 'id="message-intel-summary-24h"' in html
    assert "message-intel__summary-24h" in html
    assert "renderSummary24h" in js
    assert "summary_24h" in js
    assert ".message-intel__summary-24h" in css
