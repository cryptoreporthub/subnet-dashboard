"""Focused tests for Telegram summary bot command handling."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

from internal.message_intel import summary_bot


def test_parse_command_text_normalizes_bot_suffix():
    assert summary_bot._parse_command_text("/summary@SubnetBot 7") == ("/summary", "7")
    assert summary_bot._parse_command_text("/trending 1h") == ("/trending", "1h")


def test_summary_command_safe_when_disabled(monkeypatch):
    monkeypatch.delenv("TELEGRAM_SUMMARY_BOT", raising=False)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    assert summary_bot.summary_bot_enabled() is False


def test_handle_command_trending_and_track_formats(monkeypatch, tmp_path):
    monkeypatch.setattr(summary_bot, "_watchlist_load", lambda: {"netuids": [], "thresholds": {}, "alerts": {}})
    saved = {}

    def fake_save(netuids, thresholds=None, alerts=None):
        saved["netuids"] = list(netuids)
        saved["thresholds"] = thresholds or {}
        saved["alerts"] = alerts or {}
        return {"netuids": list(netuids), "thresholds": thresholds or {}, "alerts": alerts or {}, "updated_at": "x"}

    monkeypatch.setattr(summary_bot, "_watchlist_save", fake_save)
    monkeypatch.setattr(
        "internal.message_intel.rollup.build_trending_subnets",
        lambda **kw: [{"netuid": 7, "name": "Subnet 7", "mentions": 3, "chatter_power": 1.2}],
    )
    out = summary_bot.handle_command("/trending 1h")
    assert "ChatterPower Trending" in out
    out = summary_bot.handle_command("/track 7")
    assert "Added SN7" in out
    assert saved["netuids"] == [7]


def test_subnetsummers_command_includes_full_desk_sections(monkeypatch):
    monkeypatch.setattr(summary_bot, "_registry_subnet_names", lambda: {7: "Subnet Seven"})
    monkeypatch.setattr(
        "internal.message_intel.rollup.build_24h_summary",
        lambda **kw: {
            "message_count": 12,
            "high_conviction_count": 4,
        },
    )
    monkeypatch.setattr(
        "internal.message_intel.rollup.build_trending_subnets",
        lambda **kw: [{
            "netuid": 7,
            "name": "Subnet Seven",
            "mentions": 3,
            "chatter_power": 1.2,
            "why": "velocity × conviction × quality",
        }],
    )
    monkeypatch.setattr(
        "internal.message_intel.rollup.build_high_conviction_strip",
        lambda **kw: [{
            "netuid": 7,
            "direction": "up",
            "conviction": 88,
            "content": "SN7 building",
        }],
    )
    monkeypatch.setattr(
        "internal.message_intel.rollup.build_reaction_crowns",
        lambda **kw: [{
            "emoji": "🔥",
            "label": "Hype",
            "display_name": "@alpha",
            "count": 5,
        }],
    )
    out = summary_bot.handle_command("/subnetsummers")
    assert "Subnet ranks" in out
    assert "SN7 Subnet Seven" in out
    assert "Chatter" in out
    assert "SN7 building" in out
    assert "Reactions" in out
    assert "@alpha" in out


def test_summary_subnet_uses_current_qualified_calls(monkeypatch):
    monkeypatch.setattr(
        "internal.message_intel.rollup.build_subnet_telegram_conviction",
        lambda **kw: {
            "items": [{
                "netuid": 7,
                "label": "bullish",
                "call_count": 2,
                "contributor_count": 1,
                "current_calls": [{"direction": "up", "content": "SN7 building"}],
            }]
        },
    )
    out = summary_bot.handle_command("/summary SN7")
    assert "SN7 Telegram summary" in out
    assert "SN7 building" in out


def test_handle_command_who_and_alerts(monkeypatch):
    monkeypatch.setattr(
        "internal.message_intel.rollup.build_author_reliability_rows",
        lambda **kw: [{"author_id": "id:u1", "author_name": "Alpha", "author_username": "alpha", "message_count": 2, "accuracy_pct": 80.0}],
    )
    state = {"alerts": {}}
    monkeypatch.setattr(summary_bot, "_watchlist_load", lambda owner=None: {"netuids": [7], "thresholds": {}, "alerts": state["alerts"]})
    monkeypatch.setattr(
        summary_bot,
        "_watchlist_save",
        lambda netuids, thresholds=None, alerts=None, owner=None: state.update({"alerts": alerts or {}}) or {"netuids": netuids, "thresholds": thresholds or {}, "alerts": alerts or {}, "updated_at": "x"},
    )
    msg = {"author_id": "42", "author_username": "alpha", "author_name": "Alpha", "chat": {"id": 1}}
    who = summary_bot.handle_command("/who alpha")
    assert "Author Leaderboard" in who
    alerts = summary_bot.handle_command("/alerts on", message=msg)
    assert "Alerts turned on" in alerts
    assert state["alerts"]["id:42"]["enabled"] is True


def test_process_update_ignores_unrelated_commands(monkeypatch):
    called = {"n": 0}
    monkeypatch.setattr(summary_bot, "send_message", lambda *a, **k: called.update(n=called["n"] + 1) or {"ok": True})
    summary_bot._process_update({"message": {"text": "/unknown", "chat": {"id": 1}}})
    assert called["n"] == 0


def test_process_update_rate_limits_same_chat_and_command(monkeypatch):
    summary_bot._last_command_at.clear()
    replies = []
    monkeypatch.setattr(summary_bot, "handle_command", lambda *a, **k: replies.append("handled") or "ok")
    monkeypatch.setattr(summary_bot, "send_message", lambda *a, **k: {"ok": True})
    update = {"message": {"text": "/trending", "chat": {"id": 99}}}
    summary_bot._process_update(update)
    summary_bot._process_update(update)
    assert replies == ["handled"]
