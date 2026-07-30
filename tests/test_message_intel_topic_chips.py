"""PR4 — topic chips v1."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from internal.message_intel.topic_tags import classify_message_topics
from server import app


def test_classify_message_topics_fixture():
    text = "Validator emissions are driving alpha returns — bullish market for TAO."
    tags = classify_message_topics(text)
    assert "validator" in tags
    assert "emissions" in tags
    assert "alpha" in tags
    assert "market" in tags


def test_classify_message_topics_empty():
    assert classify_message_topics("") == []
    assert classify_message_topics("   ") == []


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


def test_list_messages_includes_topics_and_filter(client):
    payload = {
        "source": "telegram",
        "group_name": "SubnetAlpha",
        "content": "New partnership with a major validator — emissions schedule update.",
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "author_id": "u-topic",
        "author_name": "TopicTester",
    }
    with patch("internal.message_intel.engine._load_pipeline") as mock_pipe:
        from message_intel.nlp_engine import NLPAnalyzer

        mock_pipe.return_value = (
            NLPAnalyzer(),
            type("PT", (), {"db": None, "snapshot": lambda *a, **k: None})(),
        )
        assert client.post("/api/message-intel/ingest", json=payload).json()["status"] == "success"

    listed = client.get("/api/message-intel?limit=5").json()
    assert listed["count"] >= 1
    row = listed["messages"][0]
    assert "topics" in row
    assert "partnership" in row["topics"]
    assert "validator" in row["topics"]

    filtered = client.get("/api/message-intel?limit=5&topic=market").json()
    assert filtered["count"] == 0
    assert filtered.get("filtered_empty") is True

    partnership = client.get("/api/message-intel?limit=5&topic=partnership").json()
    assert partnership["count"] >= 1
    assert partnership["messages"][0]["id"] == row["id"]
