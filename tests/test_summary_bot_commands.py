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
        "internal.message_intel.rollup.build_subnet_chatter_summary",
        lambda **kw: {
            "netuid": 7,
            "name": "Subnet Seven",
            "mention_count": 3,
            "author_count": 2,
            "sentiment": "Bullish",
            "avg_conviction": 72.0,
            "bullish_mentions": 2,
            "bearish_mentions": 0,
            "snippets": [{"content": "SN7 building", "conviction": 72}],
            "empty": False,
        },
    )
    monkeypatch.setattr(
        "internal.message_intel.rollup.build_subnet_telegram_conviction",
        lambda **kw: {
            "items": [{
                "netuid": 7,
                "label": "bullish",
                "ready": True,
                "score": 42,
                "call_count": 2,
                "contributor_count": 1,
                "current_calls": [{"direction": "up", "content": "SN7 building"}],
            }]
        },
    )
    out = summary_bot.handle_command("/summary SN7")
    assert "Subnet Seven (SN7)" in out
    assert "What they're saying" in out
    assert "SN7 building" in out
    assert "Proven-caller consensus" in out


def test_summary_subnet_shows_chatter_without_qualified_calls(monkeypatch):
    monkeypatch.setattr(
        "internal.message_intel.rollup.build_subnet_chatter_summary",
        lambda **kw: {
            "netuid": 25,
            "name": "Mainframe",
            "mention_count": 4,
            "author_count": 3,
            "sentiment": "Cautious",
            "avg_conviction": 58.0,
            "bullish_mentions": 1,
            "bearish_mentions": 1,
            "snippets": [{"content": "Mainframe emissions already priced in", "conviction": 55}],
            "empty": False,
        },
    )
    monkeypatch.setattr(
        "internal.message_intel.rollup.build_subnet_telegram_conviction",
        lambda **kw: {"items": [{"netuid": 25, "current_calls": []}]},
    )
    out = summary_bot.handle_command("/summary 25")
    assert "Mainframe (SN25)" in out
    assert "4 mentions" in out
    assert "avg confidence 58%" in out
    assert "Mainframe emissions already priced in" in out
    assert "No proven-caller directional bets yet" in out


def test_subnet_from_arg_accepts_hash_syntax():
    assert summary_bot._subnet_from_arg("#25") == 25
    assert summary_bot._subnet_from_arg("SN25") == 25


def test_handle_command_who_and_alerts(monkeypatch):
    monkeypatch.setattr(
        "internal.message_intel.rollup.build_author_reliability_rows",
        lambda **kw: [
            {
                "author_id": "id:u1",
                "author_name": "Alpha",
                "author_username": "alpha",
                "message_count": 2,
                "total_graded_calls": 2,
                "graded": 2,
                "accuracy_pct": 80.0,
            }
        ],
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
    assert "Alpha – 2 calls, 80% accuracy" in who
    alerts = summary_bot.handle_command("/alerts on", message=msg)
    assert "Alerts turned on" in alerts
    assert state["alerts"]["id:42"]["enabled"] is True


def test_who_without_arg_shows_top_three_graded_callers(monkeypatch):
    monkeypatch.setattr(
        "internal.message_intel.rollup.build_author_reliability_rows",
        lambda **kw: [
            {
                "author_id": "id:u1",
                "author_name": "τaoSτacker ☯️",
                "total_graded_calls": 11,
                "graded": 11,
                "accuracy_pct": 100.0,
            },
            {
                "author_id": "id:u2",
                "author_name": "Es",
                "total_graded_calls": 6,
                "graded": 6,
                "accuracy_pct": 80.0,
            },
            {
                "author_id": "id:u3",
                "author_name": "KaWis",
                "total_graded_calls": 5,
                "graded": 5,
                "accuracy_pct": 66.7,
            },
            {
                "author_id": "id:u4",
                "author_name": "Dr.dre",
                "message_count": 198,
                "total_graded_calls": 0,
                "graded": 0,
                "accuracy_pct": 87.5,
            },
        ],
    )
    who = summary_bot.handle_command("/who")
    assert "1. τaoSτacker ☯️ – 11 calls, 100% accuracy" in who
    assert "2. Es – 6 calls, 80% accuracy" in who
    assert "3. KaWis – 5 calls, 66.7% accuracy" in who
    assert "Dr.dre" not in who


def test_send_message_disables_link_preview_for_desk_links(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:ABC")
    captured = {}

    def fake_api(method, payload):
        captured["method"] = method
        captured["payload"] = payload
        return {"ok": True}

    monkeypatch.setattr(summary_bot, "_telegram_api", fake_api)
    summary_bot.send_message(
        7,
        '<a href="https://subnet-dashboard.fly.dev/subnetsummer">Open the Subnet Summers desk</a>',
        link_preview=False,
    )
    assert captured["payload"]["link_preview_options"] == {"is_disabled": True}


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
