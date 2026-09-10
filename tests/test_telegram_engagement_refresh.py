"""Engagement metrics refresh on dedup + reaction/edit update handling."""

from __future__ import annotations

import asyncio
import json


def test_save_message_dedup_refreshes_metrics(tmp_path, monkeypatch):
    monkeypatch.setenv("MESSAGE_INTEL_DB", str(tmp_path / "mi.db"))
    from internal.message_intel.store import get_db, reset_db_cache

    reset_db_cache()
    db = get_db()
    payload = {
        "source": "telegram",
        "group_id": "-1001",
        "group_name": "OfficialSubnetSummer",
        "content": "SN30 momentum building",
        "timestamp": "2026-09-10T01:00:00",
        "message_id": "555",
        "metrics": {"views": 5, "forwards": 1, "replies": 0, "reactions": [{"emoji": "\U0001F525", "count": 2}]},
    }
    mid, deduped = db.save_message(payload)
    assert not deduped
    stored = db.get_message(mid)
    assert stored["metrics"]["views"] == 5

    # Same message re-ingested with evolved metrics must refresh, not drop.
    payload["metrics"] = {"views": 9, "forwards": 2, "replies": 3, "reactions": [{"emoji": "\U0001F525", "count": 7}]}
    mid2, deduped = db.save_message(payload)
    assert deduped and mid2 == mid
    stored = db.get_message(mid)
    assert stored["metrics"]["views"] == 9
    assert stored["metrics"]["forwards"] == 2
    assert stored["metrics"]["replies"] == 3
    assert json.loads(stored["metrics"]["reactions"])[0]["count"] == 7


def test_normalize_message_captures_engagement_metrics():
    from message_intel.telegram_listener import TelegramListener

    reactions = type("R", (), {})()
    reactions.results = [type("R", (), {"reaction": type("E", (), {"emoticon": "\U0001F525"})(), "count": 4})()]

    msg = type("M", (), {})()
    msg.id = 42
    msg.text = "SN30 momentum building"
    msg.message = None
    msg.views = 120
    msg.forwards = 3
    msg.replies = type("Rep", (), {"replies": 2})()
    msg.reactions = reactions
    msg.date = None
    msg.reply_to = None

    sender = type("S", (), {})()
    sender.id = 7
    sender.first_name = "Tester"

    listener = TelegramListener(group="OfficialSubnetSummer")
    normalized = listener._normalize_message(msg, sender, -1001)
    assert normalized["metrics"]["views"] == 120
    assert normalized["metrics"]["forwards"] == 3
    assert normalized["metrics"]["replies"] == 2
    assert normalized["metrics"]["reactions"] == [{"emoji": "\U0001F525", "count": 4}]


def test_handle_reactions_update_reingests_message(tmp_path, monkeypatch):
    monkeypatch.setenv("MESSAGE_INTEL_DB", str(tmp_path / "mi.db"))
    from internal.message_intel.store import reset_db_cache

    from message_intel.telegram_listener import TelegramListener

    reset_db_cache()

    entity = type("E", (), {})()
    entity.id = -1001

    msg = type("M", (), {})()
    msg.id = 42
    msg.chat_id = -1001
    msg.text = "SN30 momentum building"
    msg.message = None
    msg.date = None
    msg.reply_to = None
    msg.views = 200
    msg.forwards = None
    msg.replies = None
    msg.reactions = None

    async def get_sender():
        return None

    msg.get_sender = get_sender

    client = type("C", (), {})()

    async def get_entity(peer):
        return entity

    async def get_messages(target, ids):
        return msg

    client.get_entity = get_entity
    client.get_messages = get_messages

    raw_update = type("U", (), {})()
    raw_update.peer = object()
    raw_update.msg_id = 42

    captured = []

    async def fake_forward(normalized):
        captured.append(normalized)

    listener = TelegramListener(group="OfficialSubnetSummer", forward_to_ingest=True)
    listener._client = client
    listener._monitor_entity = entity
    listener._forward_to_ingest = fake_forward

    asyncio.run(listener._handle_reactions_update(raw_update))
    assert captured and captured[0]["message_id"] == "42"
    assert captured[0]["group_id"] == "-1001"


def test_handle_reactions_update_ignores_other_chats(tmp_path, monkeypatch):
    monkeypatch.setenv("MESSAGE_INTEL_DB", str(tmp_path / "mi.db"))
    from internal.message_intel.store import reset_db_cache

    from message_intel.telegram_listener import TelegramListener

    reset_db_cache()

    monitor = type("E", (), {})()
    monitor.id = -1001
    other = type("E", (), {})()
    other.id = -1002

    msg = type("M", (), {})()
    msg.id = 42
    msg.chat_id = -1002
    msg.text = "other group chatter"
    msg.message = None

    async def get_sender():
        return None

    msg.get_sender = get_sender

    client = type("C", (), {})()

    async def get_entity(peer):
        return other

    async def get_messages(target, ids):
        return msg

    client.get_entity = get_entity
    client.get_messages = get_messages

    raw_update = type("U", (), {})()
    raw_update.peer = object()
    raw_update.msg_id = 42

    captured = []

    async def fake_forward(normalized):
        captured.append(normalized)

    listener = TelegramListener(group="OfficialSubnetSummer", forward_to_ingest=True)
    listener._client = client
    listener._monitor_entity = monitor
    listener._forward_to_ingest = fake_forward

    asyncio.run(listener._handle_reactions_update(raw_update))
    assert captured == []
