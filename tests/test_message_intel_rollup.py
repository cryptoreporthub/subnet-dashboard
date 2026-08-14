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
    assert "reaction_crowns" in authors
    assert topics["status"] == "success"
    assert "topics" in topics


def test_trending_v2_orders_by_quality_and_explains(monkeypatch):
    from internal.message_intel import rollup

    now = datetime.now(timezone.utc)
    rows = [
        {"timestamp": (now - timedelta(minutes=30)).isoformat(), "author_id": "a1", "conviction": 90, "sentiment": "bullish", "content": "SN1", "entities_json": json.dumps({"subnets": [1]})},
        {"timestamp": (now - timedelta(minutes=20)).isoformat(), "author_id": "a1", "conviction": 90, "sentiment": "bullish", "content": "SN1", "entities_json": json.dumps({"subnets": [1]})},
        {"timestamp": (now - timedelta(minutes=10)).isoformat(), "author_id": "a2", "conviction": 90, "sentiment": "bullish", "content": "SN2", "entities_json": json.dumps({"subnets": [2]})},
    ]
    monkeypatch.setattr(rollup, "_load_message_rows", lambda db=None: rows)
    monkeypatch.setattr(
        rollup,
        "_author_reliability_rows",
        lambda db=None: {"a1": {"total_messages": 10, "correct_predictions": 9}, "a2": {"total_messages": 2, "correct_predictions": 1}},
    )
    monkeypatch.setattr(rollup, "_netuids_from_row", lambda row: [1] if "SN1" in row["content"] else [2])

    items = rollup.build_trending_subnets(limit=2, rank_hours=1, window_hours=24)
    assert items[0]["netuid"] == 1
    assert "why" in items[0]
    assert "chatter_power" in items[0]
    assert "delta" in items[0]


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
    crowns = listed.get("meta", {}).get("reaction_crowns") or []
    assert isinstance(crowns, list)
    fire = next((c for c in crowns if c.get("key") == "fire"), None)
    thumbs = next((c for c in crowns if c.get("key") == "thumbs"), None)
    assert fire is not None
    assert fire["author_username"] == "alpha"
    assert fire["count"] == 5
    assert fire["emoji"] == "🔥"
    assert thumbs is not None
    assert thumbs["author_username"] == "beta"
    assert thumbs["count"] == 2

    authors = client.get("/api/message-intel/authors?days=7&limit=8").json()
    assert authors["status"] == "success"
    assert authors["count"] >= 1
    top = authors["authors"][0]
    assert top["author_name"]
    assert top["message_count"] >= 1
    assert "influence_score" in top
    assert "reactions" in top
    assert top["reactions"].get("fire", 0) >= 5
    # Light reaction boost raises Alpha above Beta even with similar base influence.
    assert top["author_username"] == "alpha"
    assert any(c.get("key") == "fire" for c in authors.get("reaction_crowns") or [])
    assert "accuracy_pct" in top
    assert "strike_rate_pct" in top
    assert "correct_predictions" in top
    assert "total_graded_calls" in top
    assert "caution" in top


def test_author_reliability_rows_caution_and_receipts(intel_env):
    from internal.message_intel.store import Database
    from internal.message_intel.rollup import build_author_reliability_rows

    db = Database(intel_env["db_path"])
    db.upsert_author_reliability(
        {
            "author_id": "u1",
            "author_name": "Alice",
            "total_messages": 4,
            "correct_predictions": 3,
            "accuracy_score": 0.75,
        }
    )
    rows = build_author_reliability_rows(days=30, limit=8, db=db)
    assert rows[0]["caution"] is True
    assert rows[0]["graded_calls_caution"] is True
    assert "receipt_friendly" in rows[0]


def test_trending_v2_endpoint(client):
    payload = client.get("/api/message-intel/trending-v2?limit=3&rank_hours=1&window_hours=24").json()
    assert payload["status"] == "success"
    assert "items" in payload
    assert "trending" in payload


def test_rollup_recognizes_explicit_subnet_mentions_without_entities():
    from internal.message_intel.rollup import _netuids_from_row

    assert _netuids_from_row({"content": "SN7 is building"}) == {7}
    assert _netuids_from_row({"content": "Subnet 12 looks strong"}) == {12}


def test_message_intel_template_has_my_desk_and_pulse():
    from jinja2 import Environment, FileSystemLoader
    env = Environment(loader=FileSystemLoader("templates"))
    tpl = env.get_template("partials/premium/message_intel_feed.html")
    html = tpl.render(message_intel={"meta": {"trending": [], "total_messages": 0}, "messages": []})
    assert "My Desk" in html
    assert "My Pulse" in html


def test_listener_template_accepts_new_trending_fields():
    from jinja2 import Environment, FileSystemLoader
    env = Environment(loader=FileSystemLoader("templates"))
    tpl = env.get_template("partials/premium/message_intel_ssr_macros.html")
    html = tpl.module.trend_rows([
        {"name": "Subnet 1", "netuid": 1, "mentions": 3, "chatter_power": 1.234, "why": "velocity × conviction × quality", "delta": 0.123, "sentiment": "Bullish"}
    ], "1h")
    assert "velocity × conviction × quality" in html


def test_reaction_crowns_unit(monkeypatch):
    """Per-emoji winners; hit-rate fields never appear on crowns."""
    from datetime import datetime, timezone

    from internal.message_intel import rollup

    now = datetime.now(timezone.utc).isoformat()
    rows = [
        {
            "timestamp": now,
            "author_id": "a",
            "author_name": "Fire Queen",
            "author_username": "fq",
            "reactions": [{"emoji": "🔥", "count": 9}, {"emoji": "❤️", "count": 1}],
            "influence_score": 1.0,
        },
        {
            "timestamp": now,
            "author_id": "b",
            "author_name": "Heart King",
            "author_username": "hk",
            "reactions": [{"emoji": "❤️", "count": 4}],
            "influence_score": 1.0,
        },
        {
            "timestamp": now,
            "author_id": "a",
            "author_name": "Fire Queen",
            "author_username": "fq",
            "reactions": [{"emoji": "🔥", "count": 2}],
            "influence_score": 1.0,
        },
    ]
    monkeypatch.setattr(rollup, "_load_message_rows", lambda db=None: rows)
    crowns = rollup.build_reaction_crowns(days=7)
    by_key = {c["key"]: c for c in crowns}
    assert by_key["fire"]["count"] == 11
    assert by_key["fire"]["author_username"] == "fq"
    assert by_key["heart"]["count"] == 4
    assert by_key["heart"]["author_username"] == "hk"
    for c in crowns:
        assert "hit_rate" not in c
        assert "graded" not in c

    authors = rollup.build_weekly_authors(days=7, limit=8)
    # Optional boost: fire reactions should lift fq influence above hk.
    assert authors[0]["author_username"] == "fq"
    assert authors[0]["influence_score"] > authors[1]["influence_score"]


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


def test_week_top_comment_unit(monkeypatch):
    """Most engaged message wins; why names the dominant signal."""
    from datetime import datetime, timezone

    from internal.message_intel import rollup

    now = datetime.now(timezone.utc).isoformat()

    class FakeConn:
        def __init__(self, rows):
            self._rows = rows

        def execute(self, *_a, **_k):
            return self

        def fetchall(self):
            return self._rows

        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

    class FakeDb:
        def __init__(self, rows):
            self._rows = rows

        def _connect(self):
            return FakeConn(self._rows)

    rows = [
        {
            "id": 1,
            "author_id": "a",
            "author_name": "Quiet",
            "author_username": "q",
            "content": "low engagement note",
            "timestamp": now,
            "created_at": now,
            "source": "telegram",
            "views": 10,
            "forwards": 0,
            "replies": 0,
            "reactions": json.dumps([{"emoji": "👍", "count": 1}]),
        },
        {
            "id": 2,
            "author_id": "b",
            "author_name": "Viral",
            "author_username": "viral",
            "content": "SN14 just printed — watch the flow",
            "timestamp": now,
            "created_at": now,
            "source": "telegram",
            "views": 40,
            "forwards": 2,
            "replies": 6,
            "reactions": json.dumps([{"emoji": "🔥", "count": 12}, {"emoji": "🚀", "count": 3}]),
        },
    ]
    monkeypatch.setattr(rollup, "get_db", lambda: FakeDb(rows))
    top = rollup.build_week_top_comment(days=7)
    assert top is not None
    assert top["id"] == 2
    assert top["author_username"] == "viral"
    assert top["reaction_total"] == 15
    assert top["replies"] == 6
    assert top["why"] in {"Most reacted", "Most replied", "Most viewed", "Most engaged", "Most forwarded"}
    assert "SN14" in top["content"]


def test_week_top_comment_in_meta(client, monkeypatch):
    from internal.message_intel import rollup

    fake = {
        "id": 99,
        "author_name": "Scout",
        "author_username": "scout",
        "display_name": "@scout",
        "content": "Biggest thread of the week",
        "views": 200,
        "forwards": 4,
        "replies": 11,
        "reaction_total": 18,
        "top_reaction": {"key": "fire", "emoji": "🔥", "count": 12},
        "engagement_score": 400,
        "why": "Most reacted",
        "days": 7,
        "timestamp": "2026-07-28T12:00:00Z",
    }
    monkeypatch.setattr(rollup, "build_week_top_comment", lambda **kw: fake)
    listed = client.get("/api/message-intel").json()
    assert listed["meta"]["week_top_comment"]["id"] == 99
    assert listed["meta"]["week_top_comment"]["why"] == "Most reacted"


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


def test_subnet_telegram_conviction_weights_qualified_callers_and_bounds_score(monkeypatch):
    """Only evidence-qualified authors vote; opposing calls produce mixed."""
    from internal.message_intel import rollup

    now = datetime.now(timezone.utc)
    def row(i, author, direction, outcome=None, hours=1):
        return {
            "id": i, "source": "telegram", "author_id": author, "author_name": author,
            "timestamp": (now - timedelta(hours=hours)).isoformat(), "content": "SN7 call",
            "entities_json": json.dumps({"subnets": ["Subnet 7"]}), "verdict": "bullish" if direction == "up" else "bearish",
            "predicted_direction": direction, "conviction": 80, "tao_usd_price": 1.0,
            "outcome": outcome, "pump_pct_max": 5 if outcome == "pump" else None,
        }
    # Each caller has five scored resolved calls, then one fresh current call.
    rows = [row(i, "bull", "up", "pump", hours=96 + i) for i in range(1, 6)]
    rows += [row(i, "bear", "down", "dump", hours=96 + i) for i in range(6, 11)]
    rows += [row(11, "bull", "up"), row(12, "bear", "down")]
    monkeypatch.setattr(rollup, "_conviction_rows", lambda db=None: rows)
    result = rollup.build_subnet_telegram_conviction()
    item = result["items"][0]
    assert item["ready"] is True
    assert item["label"] == "mixed"
    assert -100 <= item["score"] <= 100
    assert item["call_count"] == 2
    assert item["contributor_count"] == 2
    assert len(item["resolved_receipts"]) >= 1


def test_subnet_telegram_conviction_insufficient_and_stale_calls(monkeypatch):
    from internal.message_intel import rollup

    now = datetime.now(timezone.utc)
    base = {
        "id": 1, "source": "telegram", "author_id": "a", "author_name": "A",
        "content": "SN8 call", "entities_json": json.dumps({"subnets": ["Subnet 8"]}),
        "verdict": "bullish", "predicted_direction": "up", "conviction": 80, "tao_usd_price": 1.0,
    }
    history = [{**base, "id": i, "timestamp": (now - timedelta(hours=100 + i)).isoformat(), "outcome": "pump", "pump_pct_max": 4} for i in range(2, 7)]
    stale = {**base, "id": 9, "timestamp": (now - timedelta(hours=80)).isoformat(), "outcome": None}
    monkeypatch.setattr(rollup, "_conviction_rows", lambda db=None: [*history, stale])
    item = rollup.build_subnet_telegram_conviction()["items"][0]
    assert item["state"] == "insufficient_data"
    assert item["score"] is None
    assert item["call_count"] == 0


def test_subnet_telegram_conviction_excludes_resolved_rows_from_current_votes(monkeypatch):
    from internal.message_intel import rollup

    now = datetime.now(timezone.utc)
    def row(mid, outcome=None, price=1.0):
        return {
            "id": mid, "source": "telegram", "author_id": "a", "author_name": "A",
            "content": "SN9 call", "entities_json": json.dumps({"subnets": ["Subnet 9"]}),
            "timestamp": (now - timedelta(hours=1)).isoformat(),
            "verdict": "bullish", "predicted_direction": "up", "conviction": 80,
            "tao_usd_price": price, "outcome": outcome,
            "pump_pct_max": 5 if outcome == "pump" else None,
        }

    history = [
        {
            **row(10 + i, "pump"),
            "timestamp": (now - timedelta(hours=96 + i)).isoformat(),
        }
        for i in range(5)
    ]
    monkeypatch.setattr(rollup, "_conviction_rows", lambda db=None: [*history, row(1, "pump"), row(2)])
    item = rollup.build_subnet_telegram_conviction()["items"][0]
    assert item["call_count"] == 1
    assert all(call["message_id"] != 1 for call in item["current_calls"])


def test_telegram_divergence_stories_compare_only_resolved_qualified_receipts(monkeypatch):
    """A story uses timestamped Telegram proof receipts, never chatter or pending rows."""
    from internal.message_intel import rollup

    now = datetime.now(timezone.utc)

    def row(mid, author, direction, outcome, *, conviction=80, hours=26):
        return {
            "id": mid, "source": "telegram", "author_id": author, "author_name": author,
            "timestamp": (now - timedelta(hours=hours)).isoformat(), "content": "SN7 call",
            "entities_json": json.dumps({"subnets": ["Subnet 7"]}),
            "verdict": "bullish" if direction == "up" else "bearish",
            "predicted_direction": direction, "conviction": conviction, "tao_usd_price": 1.0,
            "outcome": outcome, "pump_pct_max": 4 if outcome == "pump" else -4,
            "price_24h": 1.04 if outcome == "pump" else .96,
            "price_24h_recorded_at": (now - timedelta(hours=1)).isoformat(),
        }

    rows = [
        row(1, "a", "up", "pump"),
        row(2, "b", "up", "pump"),
        row(3, "ignored", "up", "pump", conviction=20),
        row(4, "pending", "up", None),
    ]
    monkeypatch.setattr(rollup, "_conviction_rows", lambda db=None: rows)

    story = rollup.build_telegram_divergence_stories()["stories"][0]
    assert story["ready"] is True
    assert story["state"] == "aligned"
    assert story["label"] == "consensus-confirmed"
    assert story["consensus_direction"] == "up"
    assert story["observed_direction"] == "up"
    assert story["qualifying_call_count"] == 2
    assert story["pending_qualifying_call_count"] == 1
    assert {receipt["message_id"] for receipt in story["receipts"]} == {1, 2}
    assert all(receipt["proof"]["evaluation"] == "resolved" for receipt in story["receipts"])


def test_telegram_divergence_marks_conflict_and_insufficient_data(monkeypatch):
    from internal.message_intel import rollup

    now = datetime.now(timezone.utc)

    def row(mid, author, outcome, netuid):
        return {
            "id": mid, "source": "telegram", "author_id": author, "author_name": author,
            "timestamp": (now - timedelta(hours=26)).isoformat(), "content": f"SN{netuid} call",
            "entities_json": json.dumps({"subnets": [netuid]}), "verdict": "bullish",
            "predicted_direction": "up", "conviction": 80, "tao_usd_price": 1.0,
            "outcome": outcome, "pump_pct_max": -4 if outcome == "dump" else 4,
            "price_24h": .96 if outcome == "dump" else 1.04,
            "price_24h_recorded_at": (now - timedelta(hours=1)).isoformat(),
        }

    rows = [row(1, "a", "dump", 7), row(2, "b", "dump", 7), row(3, "solo", "pump", 8)]
    monkeypatch.setattr(rollup, "_conviction_rows", lambda db=None: rows)
    stories = {story["netuid"]: story for story in rollup.build_telegram_divergence_stories()["stories"]}
    assert stories[7]["state"] == "diverged"
    assert stories[7]["label"] == "loud-but-wrong"
    assert stories[7]["observed_direction"] == "down"
    assert stories[8]["state"] == "insufficient_data"
    assert stories[8]["ready"] is False
    assert "Needs 2 resolved" in stories[8]["insufficient_reason"]


def test_telegram_divergence_requires_recorded_24h_price(monkeypatch):
    """An early resolved outcome cannot be presented as a 24h story."""
    from internal.message_intel import rollup

    now = datetime.now(timezone.utc)
    rows = [
        {
            "id": mid, "source": "telegram", "author_id": author, "author_name": author,
            "timestamp": (now - timedelta(hours=4)).isoformat(), "content": "SN7 call",
            "entities_json": json.dumps({"subnets": [7]}), "verdict": "bearish",
            "predicted_direction": "down", "conviction": 80, "tao_usd_price": 1.0,
            "outcome": "dump", "pump_pct_max": None, "price_24h": None,
            "price_24h_recorded_at": None,
        }
        for mid, author in ((1, "a"), (2, "b"))
    ]
    monkeypatch.setattr(rollup, "_conviction_rows", lambda db=None: rows)

    story = rollup.build_telegram_divergence_stories()["stories"][0]
    assert story["ready"] is False
    assert story["state"] == "insufficient_data"
    assert story["qualifying_call_count"] == 0
    assert story["pending_qualifying_call_count"] == 2
    assert story["receipts"] == []


def test_telegram_divergence_rejects_unmatured_24h_record(monkeypatch):
    """A populated price_24h cannot masquerade as mature without its timestamp."""
    from internal.message_intel import rollup

    now = datetime.now(timezone.utc)
    rows = [
        {
            "id": mid, "source": "telegram", "author_id": author, "author_name": author,
            "timestamp": (now - timedelta(hours=4)).isoformat(), "content": "SN7 call",
            "entities_json": json.dumps({"subnets": [7]}), "verdict": "bullish",
            "predicted_direction": "up", "conviction": 80, "tao_usd_price": 1.0,
            "outcome": "pump", "pump_pct_max": 4, "price_24h": 1.04,
            "price_24h_recorded_at": now.isoformat(),
        }
        for mid, author in ((1, "a"), (2, "b"))
    ]
    monkeypatch.setattr(rollup, "_conviction_rows", lambda db=None: rows)
    story = rollup.build_telegram_divergence_stories()["stories"][0]
    assert story["ready"] is False
    assert story["pending_qualifying_call_count"] == 2
