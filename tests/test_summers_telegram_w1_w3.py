"""SS-TG W1–W3 — detail API, proof band, high-conviction strip."""

from __future__ import annotations

import json
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


def _seed_message(db, *, conviction: float = 72.0, with_outcome: bool = False):
    mid, _ = db.save_message(
        {
            "source": "telegram",
            "group_name": "OfficialSubnetSummer",
            "author_name": "Nick",
            "content": "SN25 is heating up",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    )
    db.save_analysis(
        mid,
        {
            "sentiment": "bullish",
            "entities": {"subnets": ["SN25"]},
            "influence_score": 0.5,
        },
    )
    db.save_verdict(
        mid,
        {
            "verdict": "bullish",
            "conviction": conviction,
            "reasoning": "Strong subnet mention with momentum language.",
            "predicted_direction": "up",
        },
    )
    db.save_price_snapshot(mid, 1.25, netuid=25)
    if with_outcome:
        db.save_price_outcome(
            mid,
            {
                "price_1h": 1.3,
                "outcome": "pump",
                "pump_pct_max": 4.2,
            },
        )
    return mid


def test_message_detail_includes_reasoning_and_outcome(client, intel_env):
    mid = _seed_message(intel_env, with_outcome=True)
    body = client.get(f"/api/message-intel/detail/{mid}").json()
    assert body["status"] == "success"
    assert body["detail"]["reasoning"]
    assert body["detail"]["graded"] is True
    assert body["detail"]["price_outcome"]["outcome"] == "pump"
    assert body["detail"]["netuid"] == 25


def test_list_meta_includes_proof_and_hc_strip(client, intel_env):
    _seed_message(intel_env, conviction=65.0, with_outcome=True)
    payload = client.get("/api/message-intel?limit=5").json()
    assert payload["status"] == "success"
    proof = payload["meta"].get("telegram_proof") or {}
    assert proof.get("graded", 0) >= 1
    assert "hit_rate" in proof
    strip = payload["meta"].get("high_conviction_strip") or []
    assert isinstance(strip, list)


def test_telegram_proof_band_rollup(intel_env):
    from internal.message_intel.rollup import build_telegram_proof_band

    _seed_message(intel_env, with_outcome=True)
    proof = build_telegram_proof_band(db=intel_env)
    assert proof["graded"] == 1
    assert proof["hits"] == 1
    assert proof["hit_rate"] == 100.0


def test_summers_template_has_w1_w3_markers():
    html = open("templates/partials/premium/message_intel_feed.html", encoding="utf-8").read()
    js = open("static/js/message_intel_feed.js", encoding="utf-8").read()
    assert "message-intel-proof" in html
    assert "message-intel-hc-strip" in html
    assert "message-intel-detail" in html
    assert "toggleMessageDetail" in js
    assert "renderTelegramProof" in js
