"""Phase C — message-intel live wiring, Soul-Map sync, and trail emit."""

from __future__ import annotations

import json
import os
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from server import app


@pytest.fixture
def intel_env(tmp_path, monkeypatch):
    db_path = str(tmp_path / "message_intel.db")
    soul_path = str(tmp_path / "soul_map.json")
    soul_path_obj = tmp_path / "soul_map.json"
    soul_path_obj.write_text(
        json.dumps(
            {
                "adversarial_state": {"council_weights": {"quant": 1.0, "hype": 1.0, "dark_horse": 1.0, "technical": 1.0}},
                "soul_map_state": {"learning_trail": [], "message_intel": {}},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("MESSAGE_INTEL_DB", db_path)
    monkeypatch.setenv("SOUL_MAP_PATH", soul_path)
    from internal.message_intel import store

    store.reset_db_cache()
    from internal.council import weights

    monkeypatch.setattr(weights, "SOUL_MAP_PATH", soul_path)
    yield {"db_path": db_path, "soul_path": soul_path}


@pytest.fixture
def client(intel_env):
    with TestClient(app) as c:
        yield c


def test_ingest_writes_db_soul_map_and_trail(client, intel_env):
    payload = {
        "source": "telegram",
        "group_name": "SubnetAlpha",
        "content": "Subnet 7 is extremely bullish with strong emission growth!",
        "timestamp": "2026-07-11T00:00:00Z",
    }
    with patch("internal.message_intel.engine._load_pipeline") as mock_pipe:
        from message_intel.nlp_engine import NLPAnalyzer
        from message_intel.price_tracker import PriceTracker

        nlp = NLPAnalyzer()
        mock_pipe.return_value = (nlp, type("PT", (), {"db": None, "snapshot": lambda *a, **k: None})())

        resp = client.post("/api/message-intel/ingest", json=payload)

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "success"
    assert body["message_id"] > 0
    assert body["analysis"]["sentiment"] in ("bullish", "neutral", "bearish")
    assert body["soul_map"]["trail_events"] >= 1

    soul = json.loads(open(intel_env["soul_path"], encoding="utf-8").read())
    sms = soul.get("soul_map_state") or {}
    assert sms.get("message_intel_log")
    assert "7" in (sms.get("message_intel_dispositions") or {})
    trail = sms.get("learning_trail") or []
    assert any(
        row.get("event_type") in ("signal_triggered", "conviction_update", "disposition_shift")
        for row in trail
    )


def test_batch_ingest(client, intel_env):
    batch = {
        "messages": [
            {"source": "discord", "content": "Subnet 3 bearish dump incoming", "group_name": "DiscordSN3"},
            {"source": "telegram", "content": "Subnet 12 partnership looks solid", "group_name": "TG12"},
        ]
    }
    with patch("internal.message_intel.engine._load_pipeline") as mock_pipe:
        from message_intel.nlp_engine import NLPAnalyzer

        mock_pipe.return_value = (NLPAnalyzer(), type("PT", (), {"db": None})())

        resp = client.post("/api/message-intel/ingest", json=batch)

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "success"
    assert body["ingested"] == 2
    assert body["soul_map"]["trail_events"] >= 1


def test_list_detail_chatter_patterns(client, intel_env):
    ingest = {
        "source": "telegram",
        "content": "Subnet 5 massive breakout bullish pump!",
        "group_name": "ChatterTest",
    }
    with patch("internal.message_intel.engine._load_pipeline") as mock_pipe:
        from message_intel.nlp_engine import NLPAnalyzer

        mock_pipe.return_value = (NLPAnalyzer(), type("PT", (), {"db": None, "snapshot": lambda *a, **k: None})())
        created = client.post("/api/message-intel/ingest", json=ingest).json()

    msg_id = created["message_id"]

    listed = client.get("/api/message-intel/list").json()
    assert listed["status"] == "success"
    assert listed["count"] >= 1
    assert listed["meta"]["total_messages"] >= 1

    detail = client.get(f"/api/message-intel/detail/{msg_id}").json()
    assert detail["status"] == "success"
    assert detail["message"]["id"] == msg_id

    chatter = client.get("/api/message-intel/chatter?min_conviction=0").json()
    assert chatter["status"] == "success"

    patterns = client.get("/api/message-intel/patterns").json()
    assert patterns["status"] == "success"
    assert "patterns" in patterns


def test_summarize_message_intel_live(intel_env):
    from internal.message_intel.engine import ingest_message
    from internal.message_intel.summary import summarize_message_intel

    with patch("internal.message_intel.engine._load_pipeline") as mock_pipe:
        from message_intel.nlp_engine import NLPAnalyzer

        mock_pipe.return_value = (NLPAnalyzer(), type("PT", (), {"db": None, "snapshot": lambda *a, **k: None})())
        ingest_message({"source": "telegram", "content": "Subnet 9 bullish momentum", "group_name": "SumTest"})

    summary = summarize_message_intel()
    assert summary["sentences"]
    assert "Message-intel" in summary["text"] or "message" in summary["text"].lower()
    assert len(summary["sentences"]) >= 2


def test_mindmap_state_includes_message_intel_summary(client, intel_env):
    with patch("internal.message_intel.engine._load_pipeline") as mock_pipe:
        from message_intel.nlp_engine import NLPAnalyzer

        mock_pipe.return_value = (NLPAnalyzer(), type("PT", (), {"db": None, "snapshot": lambda *a, **k: None})())
        client.post(
            "/api/message-intel/ingest",
            json={"source": "telegram", "content": "Subnet 2 bullish", "group_name": "MindmapPanel"},
        )

    state = client.get("/api/mindmap/state").json()
    assert state["status"] == "success"
    assert "message_intel" in state.get("summaries", {})
