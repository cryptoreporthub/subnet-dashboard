"""Phase M — social ingestion API, dedup, and Jinja context."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from server import app


@pytest.fixture
def intel_env(tmp_path, monkeypatch):
    db_path = str(tmp_path / "message_intel.db")
    soul_path = str(tmp_path / "soul_map.json")
    (tmp_path / "soul_map.json").write_text(
        json.dumps(
            {
                "adversarial_state": {
                    "council_weights": {"quant": 1.0, "hype": 1.0, "dark_horse": 1.0, "technical": 1.0}
                },
                "soul_map_state": {"learning_trail": [], "message_intel": {}},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("MESSAGE_INTEL_DB", db_path)
    monkeypatch.setenv("SOUL_MAP_PATH", soul_path)
    monkeypatch.setenv("MESSAGE_INTEL_LISTENER", "off")
    monkeypatch.setenv("ALERTS_PATH", str(tmp_path / "alerts.json"))
    from internal.message_intel import store

    store.reset_db_cache()
    from internal.council import weights

    monkeypatch.setattr(weights, "SOUL_MAP_PATH", soul_path)
    yield {"db_path": db_path}


@pytest.fixture
def client(intel_env):
    with TestClient(app) as c:
        yield c


def _ingest_payload(**overrides):
    base = {
        "source": "telegram",
        "group_id": "1001",
        "group_name": "SubnetAlpha",
        "message_id": "42",
        "content": "Subnet 7 looks extremely bullish today!",
        "timestamp": "2026-07-13T00:00:00Z",
    }
    base.update(overrides)
    return base


def test_api_message_intel_honest_empty(client):
    resp = client.get("/api/message-intel")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "success"
    assert body["messages"] == []
    assert body["count"] == 0


def test_ingest_dedup_same_channel_message_id(client):
    payload = _ingest_payload()
    with patch("internal.message_intel.engine._load_pipeline") as mock_pipe:
        from message_intel.nlp_engine import NLPAnalyzer

        mock_pipe.return_value = (
            NLPAnalyzer(),
            type(
                "PT",
                (),
                {
                    "db": None,
                    "snapshot": lambda *a, **k: None,
                    "snapshot_subnet": lambda *a, **k: None,
                },
            )(),
        )
        first = client.post("/api/message-intel/ingest", json=payload).json()
        second = client.post("/api/message-intel/ingest", json=payload).json()

    assert first["status"] == "success"
    assert first.get("deduped") is not True
    assert second["status"] == "success"
    assert second.get("deduped") is True
    assert second["message_id"] == first["message_id"]

    listed = client.get("/api/message-intel").json()
    assert listed["count"] == 1


def test_jinja_message_intel_context(client):
    with patch("internal.message_intel.engine._load_pipeline") as mock_pipe:
        from message_intel.nlp_engine import NLPAnalyzer

        mock_pipe.return_value = (
            NLPAnalyzer(),
            type(
                "PT",
                (),
                {
                    "db": None,
                    "snapshot": lambda *a, **k: None,
                    "snapshot_subnet": lambda *a, **k: None,
                },
            )(),
        )
        client.post("/api/message-intel/ingest", json=_ingest_payload())

    html = client.get("/").text
    assert 'id="section-social"' in html
    api = client.get("/api/message-intel").json()
    assert api["count"] >= 1


def test_social_sentiment_for_home_prioritizes_pick(intel_env):
    from internal.message_intel.context import social_sentiment_for_home
    from internal.message_intel.store import get_db

    db = get_db()
    for msg_id, content, netuid in (
        ("7a", "Subnet 7 looks bullish", 7),
        ("99a", "Subnet 99 chatter", 99),
    ):
        mid, _ = db.save_message(
            {
                "source": "telegram",
                "group_id": "g1",
                "message_id": msg_id,
                "content": content,
            }
        )
        db.save_analysis(
            mid,
            {
                "sentiment": "bullish",
                "sentiment_confidence": 0.8,
                "entities": {"subnets": [f"subnet {netuid}"]},
            },
        )
        db.save_price_snapshot(mid, 1.0, netuid=netuid)

    subnets = [{"netuid": 7, "name": "Apex"}, {"netuid": 99, "name": "SN99"}]
    rows = social_sentiment_for_home(subnets, pick_netuid=99, limit=6)
    assert rows
    assert rows[0]["netuid"] == 99


def test_build_message_intel_context_module():
    from internal.message_intel.context import build_message_intel_context

    ctx = build_message_intel_context()
    assert "message_intel" in ctx
    assert isinstance(ctx["message_intel"].get("messages"), list)
    assert "social_sentiment" in ctx
    assert isinstance(ctx["social_sentiment"], list)


def test_netuid_sentiment_rollup_from_entities(intel_env):
    from internal.message_intel.store import get_db

    db = get_db()
    mid, _ = db.save_message(
        {
            "source": "telegram",
            "group_id": "g1",
            "message_id": "99",
            "content": "Subnet 7 looks bullish",
        }
    )
    db.save_analysis(
        mid,
        {
            "sentiment": "bullish",
            "sentiment_confidence": 0.8,
            "entities": {"subnets": ["subnet 7"]},
        },
    )
    db.save_price_snapshot(mid, 1.0, netuid=7)

    rollup = db.netuid_sentiment_rollup()
    assert len(rollup) == 1
    assert rollup[0]["netuid"] == 7
    assert rollup[0]["label"] == "bullish"
    assert rollup[0]["mentions"] >= 1


def test_build_social_sentiment_rows(intel_env):
    from internal.message_intel.context import build_social_sentiment_rows
    from internal.message_intel.store import get_db

    db = get_db()
    mid, _ = db.save_message(
        {
            "source": "telegram",
            "group_id": "g2",
            "message_id": "100",
            "content": "SN 3 bearish dump",
        }
    )
    db.save_analysis(
        mid,
        {
            "sentiment": "bearish",
            "sentiment_confidence": 0.7,
            "entities": {"subnets": ["sn 3"]},
        },
    )

    rows = build_social_sentiment_rows(
        [{"netuid": 3, "name": "Gamma"}],
        limit=6,
    )
    assert len(rows) == 1
    assert rows[0]["netuid"] == 3
    assert rows[0]["name"] == "Gamma"
    assert rows[0]["label"] == "bearish"
    assert rows[0]["mentions"] == 1


def test_homepage_social_sentiment_from_message_intel(client):
    with patch("internal.message_intel.engine._load_pipeline") as mock_pipe:
        from message_intel.nlp_engine import NLPAnalyzer

        mock_pipe.return_value = (
            NLPAnalyzer(),
            type("PT", (), {"db": None, "snapshot": lambda *a, **k: None, "snapshot_subnet": lambda *a, **k: None})(),
        )
        client.post(
            "/api/message-intel/ingest",
            json=_ingest_payload(content="Subnet 7 looks extremely bullish today!"),
        )

    html = client.get("/").text
    assert "section-social" in html
    assert "SN7" in html or "Subnet 7" in html or "bullish" in html.lower()


def test_api_message_intel_social_honest_empty(client):
    resp = client.get("/api/message-intel/social")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "success"
    assert body["empty"] is True
    assert body["rows"] == []


def test_health_ok(client):
    assert client.get("/health").text.strip() == "OK"
