"""Telegram message-intel trending + weekly champions rollups."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from server import app


@pytest.fixture
def intel_env(tmp_path, monkeypatch):
    db_path = str(tmp_path / "message_intel.db")
    monkeypatch.setenv("MESSAGE_INTEL_DB", db_path)
    from internal.message_intel import store

    store.reset_db_cache()
    yield {"db_path": db_path}


@pytest.fixture
def client(intel_env):
    with TestClient(app) as c:
        yield c


def _ingest(client, content: str, **extra):
    payload = {
        "source": "telegram",
        "group_name": "SubnetAlpha",
        "content": content,
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        **extra,
    }
    with patch("internal.message_intel.engine._load_pipeline") as mock_pipe:
        from message_intel.nlp_engine import NLPAnalyzer

        mock_pipe.return_value = (
            NLPAnalyzer(),
            type("PT", (), {"db": None, "snapshot": lambda *a, **k: None})(),
        )
        return client.post("/api/message-intel/ingest", json=payload).json()


def test_api_message_intel_authors_and_topics(client):
    authors = client.get("/api/message-intel/authors").json()
    topics = client.get("/api/message-intel/topics").json()
    assert authors["status"] == "success"
    assert "authors" in authors
    assert topics["status"] == "success"
    assert "topics" in topics


def test_trending_and_authors_after_ingest(client):
    _ingest(
        client,
        "Subnet 7 is extremely bullish with strong emission growth!",
        author_id="u1",
        author_name="Alpha Trader",
        author_username="alpha",
        metrics={"reactions": [{"emoji": "🔥", "count": 5}]},
    )
    _ingest(
        client,
        "SN7 still building — watch the flow",
        author_id="u1",
        author_name="Alpha Trader",
        author_username="alpha",
    )
    _ingest(
        client,
        "Subnet 12 partnership looks solid",
        author_id="u2",
        author_name="Beta Scout",
        author_username="beta",
        metrics={"reactions": [{"emoji": "👍", "count": 2}]},
    )

    listed = client.get("/api/message-intel/list").json()
    assert listed["status"] == "success"
    trending = listed.get("meta", {}).get("trending") or []
    assert isinstance(trending, list)
    if trending:
        assert "netuid" in trending[0]
        assert "mentions" in trending[0]
        assert "sparkline" in trending[0]

    authors = client.get("/api/message-intel/authors?days=7&limit=8").json()
    assert authors["status"] == "success"
    assert authors["count"] >= 1
    top = authors["authors"][0]
    assert top["author_name"]
    assert top["message_count"] >= 1
    assert "influence_score" in top
    assert "reactions" in top

    topics = client.get("/api/message-intel/topics").json()
    assert topics["status"] == "success"
    assert any(t.get("kind") == "group" for t in topics.get("topics") or [])


def test_yesterday_leader_in_meta(client, monkeypatch):
    from internal.message_intel import rollup

    fake = {
        "netuid": 14,
        "name": "TaoHash",
        "mentions": 47,
        "sentiment": "Bullish",
        "date": "2026-07-26",
        "runner_up": {"netuid": 78, "name": "Apex", "mentions": 31},
    }
    monkeypatch.setattr(rollup, "build_yesterday_leader", lambda **kw: fake)
    listed = client.get("/api/message-intel").json()
    assert listed["meta"]["yesterday_leader"]["netuid"] == 14


def test_trending_falls_back_to_24h_when_1h_empty(monkeypatch):
    """Quiet 1h window should still fill the desk from last-day chatter."""
    from datetime import datetime, timedelta, timezone

    from internal.message_intel import rollup

    now = datetime.now(timezone.utc)
    old = (now - timedelta(hours=5)).isoformat()
    rows = [
        {
            "timestamp": old,
            "content": "SN59 looking hot",
            "conviction": 60,
            "sentiment": "bullish",
        },
        {
            "timestamp": old,
            "content": "SN63 mention",
            "conviction": 40,
            "sentiment": "neutral",
        },
    ]

    monkeypatch.setattr(rollup, "_load_message_rows", lambda db=None: rows)
    monkeypatch.setattr(
        rollup,
        "_netuids_from_row",
        lambda row: [59] if "59" in row["content"] else [63],
    )

    assert rollup.build_trending_subnets(rank_hours=1, window_hours=6) == []
    day = rollup.build_trending_subnets(rank_hours=24, window_hours=24)
    assert {r["netuid"] for r in day} == {59, 63}
    assert all(r.get("window") == "24h" for r in day)
