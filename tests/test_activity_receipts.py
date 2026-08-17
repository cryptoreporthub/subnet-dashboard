"""Activity receipts — reactions/influence show in caller receipts drawer."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest


@pytest.fixture
def intel_db(tmp_path, monkeypatch):
    db_path = str(tmp_path / "message_intel.db")
    monkeypatch.setenv("MESSAGE_INTEL_DB", db_path)
    from internal.message_intel import store

    store.reset_db_cache()
    yield store.get_db(db_path)


def _seed_activity(db, *, author_id="1403956677", reactions=None, influence=0.5, content="Thanks!"):
    ts = datetime.now(timezone.utc).isoformat()
    mid, _ = db.save_message(
        {
            "source": "telegram",
            "group_id": "-1001",
            "author_id": author_id,
            "author_name": "Gavin",
            "author_username": "pepeleplutus",
            "content": content,
            "timestamp": ts,
            "message_id": "215000",
        }
    )
    db.save_analysis(mid, {"influence_score": influence, "entities": {"subnets": []}})
    if reactions:
        with db._connect() as conn:
            conn.execute(
                "INSERT INTO message_metrics (message_id, reactions) VALUES (?, ?)",
                (mid, __import__("json").dumps(reactions)),
            )
    return mid


def test_activity_receipts_for_reaction_messages(intel_db):
    from internal.message_intel.rollup import list_telegram_caller_receipts

    _seed_activity(
        intel_db,
        reactions=[{"emoji": "🔥", "count": 3}],
        influence=0.24,
        content="https://x.com/gavinzaentz/status/123",
    )
    result = list_telegram_caller_receipts(author_id="id:1403956677", days=7, db=intel_db)
    assert result["receipts"] == []
    assert result["activity_total"] == 1
    act = result["activity"][0]
    assert act["kind"] == "activity"
    assert act["reactions"]["fire"] == 3
    assert act["reaction_boost"] == 9.0


def test_legacy_reliability_trace_in_receipts_response(intel_db):
    from internal.message_intel.rollup import list_telegram_caller_receipts

    intel_db.upsert_author_reliability(
        {
            "author_id": "1403956677",
            "author_name": "Gavin",
            "total_messages": 7,
            "correct_predictions": 7,
            "accuracy_score": 1.0,
        }
    )
    result = list_telegram_caller_receipts(author_id="id:1403956677", days=7, db=intel_db)
    legacy = result["legacy_reliability"]
    assert legacy is not None
    assert legacy["total_messages"] == 7
    assert legacy["correct_predictions"] == 7
    assert legacy["source"] == "author_reliability"
