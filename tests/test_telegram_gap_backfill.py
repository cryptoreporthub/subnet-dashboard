"""Gap-aware Telegram backfill after listener disconnect."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import pytest


def test_last_telegram_external_id_from_db(tmp_path, monkeypatch):
    monkeypatch.setenv("MESSAGE_INTEL_DB", str(tmp_path / "mi.db"))
    from internal.message_intel.store import get_db, last_telegram_external_id, reset_db_cache

    reset_db_cache()
    db = get_db()
    mid, _ = db.save_message(
        {
            "source": "telegram",
            "group_id": "-1001",
            "group_name": "OfficialSubnetSummer",
            "content": "older",
            "timestamp": "2026-07-28T01:00:00",
            "message_id": "208700",
        }
    )
    assert mid
    db.save_message(
        {
            "source": "telegram",
            "group_id": "-1001",
            "group_name": "OfficialSubnetSummer",
            "content": "newer",
            "timestamp": "2026-07-28T05:56:00",
            "message_id": "208736",
        }
    )
    assert last_telegram_external_id() == 208736


def test_last_telegram_group_id_from_db(tmp_path, monkeypatch):
    monkeypatch.setenv("MESSAGE_INTEL_DB", str(tmp_path / "mi.db"))
    from internal.message_intel.store import get_db, last_telegram_group_id, reset_db_cache

    reset_db_cache()
    db = get_db()
    db.save_message(
        {
            "source": "telegram",
            "group_id": "-1002480957486",
            "group_name": "OfficialSubnetSummer",
            "content": "hello",
            "timestamp": "2026-07-28T05:56:00",
            "message_id": "208736",
        }
    )
    assert last_telegram_group_id() == -1002480957486


def test_entity_lookup_keys_prefers_numeric_id(monkeypatch):
    monkeypatch.setenv("TELEGRAM_GROUP_ID", "-1002480957486")
    from message_intel.telegram_listener import TelegramListener

    keys = TelegramListener(group="OfficialSubnetSummer")._entity_lookup_keys()
    assert keys[0] == -1002480957486
    assert "OfficialSubnetSummer" in keys


def test_resolve_monitor_entity_uses_db_group_id(monkeypatch, tmp_path):
    import asyncio

    monkeypatch.setenv("MESSAGE_INTEL_DB", str(tmp_path / "mi.db"))
    from internal.message_intel.store import get_db, reset_db_cache

    reset_db_cache()
    get_db().save_message(
        {
            "source": "telegram",
            "group_id": "-1002480957486",
            "group_name": "OfficialSubnetSummer",
            "content": "stored",
            "timestamp": "2026-07-28T05:56:00",
            "message_id": "1",
        }
    )

    class _Entity:
        id = -1002480957486
        title = "Subnet Summer"
        forum = False

    class _Client:
        async def get_entity(self, key):
            if key == -1002480957486:
                return _Entity()
            raise ValueError("not found")

        async def iter_dialogs(self, limit=250):
            return
            yield  # pragma: no cover

    from message_intel.telegram_listener import TelegramListener

    listener = TelegramListener(group="bad_username", forward_to_ingest=False)
    listener._client = _Client()
    entity, via = asyncio.run(listener._resolve_monitor_entity())
    assert entity.title == "Subnet Summer"
    assert "get_entity" in via


def test_normalize_message_uses_telegram_date():
    from message_intel.telegram_listener import TelegramListener

    listener = TelegramListener(forward_to_ingest=False)
    msg = type(
        "Msg",
        (),
        {
            "text": "KnightHawk subnet question",
            "message": "KnightHawk subnet question",
            "id": 208800,
            "date": datetime(2026, 7, 29, 1, 39, 0, tzinfo=timezone.utc),
            "views": None,
            "forwards": None,
            "reply_to": None,
            "reactions": None,
        },
    )()
    sender = type("Sender", (), {"id": 1, "first_name": "KnightHawk", "username": "hk"})()
    out = listener._normalize_message(msg, sender, -1002480957486)
    assert out is not None
    assert out["timestamp"].startswith("2026-07-29T01:39:00")
    assert out["message_id"] == "208800"


def test_forum_backfill_scans_topics(monkeypatch):
    import asyncio

    from message_intel.telegram_listener import TelegramListener

    seen_reply_to: list[Optional[int]] = []

    class _Entity:
        forum = True

    class _IterClient:
        async def iter_messages(self, entity, limit=100, reply_to=None, **kw):
            seen_reply_to.append(reply_to)
            return
            yield  # pragma: no cover

    listener = TelegramListener(forward_to_ingest=False)
    listener.on_message = lambda _n: None
    listener._client = _IterClient()

    async def _fake_targets(entity):
        return [None, 42, 99]

    async def _fake_ingest(payload, snapshot_price=True):
        return {"deduped": False}

    monkeypatch.setattr(listener, "_forum_backfill_targets", _fake_targets)
    monkeypatch.setattr("internal.message_intel.engine.ingest_message", _fake_ingest)

    asyncio.run(listener._backfill_gap(_Entity(), 150, 208736))
    assert seen_reply_to == [None, 42, 99]


def test_backfill_recent_uses_min_id(monkeypatch):
    import asyncio

    from message_intel.telegram_listener import TelegramListener

    seen: list[dict] = []

    class _Msg:
        def __init__(self, mid: int):
            self.id = mid
            self.text = "gap fill message here"
            self.message = self.text
            self.date = datetime(2026, 7, 29, 2, 43, tzinfo=timezone.utc)
            self.chat_id = -1002480957486
            self.views = None
            self.forwards = None
            self.reply_to = None
            self.reactions = None

        async def get_sender(self):
            return type("S", (), {"id": 9, "first_name": "Gavin", "username": "g"})()

    class _IterClient:
        def __init__(self, messages):
            self._messages = messages

        async def iter_messages(self, entity, limit=100, **kw):
            seen.append(dict(kw, limit=limit))
            for m in self._messages:
                yield m

    def _fake_ingest(payload, snapshot_price=True):
        return {"deduped": False}

    monkeypatch.setattr("internal.message_intel.engine.ingest_message", _fake_ingest)

    listener = TelegramListener(forward_to_ingest=False)
    listener.on_message = lambda _n: None
    listener._client = _IterClient([_Msg(208737), _Msg(208738)])

    async def _run() -> None:
        await listener._backfill_recent(object(), 50, min_id=208736)

    asyncio.run(_run())
    assert seen == [{"limit": 50}]
