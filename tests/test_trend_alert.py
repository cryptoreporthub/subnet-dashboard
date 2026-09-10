"""Trending #1 takeover alert — env-gated Telegram push (SS-TG follow-on)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from internal.message_intel import summary_bot, trend_alert


TOP_ROW = {"netuid": 42, "name": "TestNet", "mentions": 3, "chatter_power": 88.0, "why": "spike in chatter"}
PREV_ROW = {"netuid": 41, "name": "OldNet", "mentions": 2, "chatter_power": 40.0, "why": "fading"}


@pytest.fixture(autouse=True)
def _reset(monkeypatch, tmp_path):
    trend_alert.stop_trend_alert_watcher()
    trend_alert._seen_chats.clear()
    monkeypatch.setattr(trend_alert, "STATE_PATH", str(tmp_path / "trend_state.json"))
    yield
    trend_alert.stop_trend_alert_watcher()
    trend_alert._seen_chats.clear()


def _patch_ranking(rows):
    return patch("internal.message_intel.rollup.build_trending_subnets", return_value=rows)


def _patch_send(ok=True):
    sends = []

    def _fake(chat_id, text, **kwargs):
        sends.append((chat_id, text))
        return {"ok": ok, "result": {"message_id": 1}}

    return patch("internal.message_intel.summary_bot.send_message", side_effect=_fake), sends


def test_watcher_env_gated(monkeypatch):
    monkeypatch.delenv("TELEGRAM_TREND_ALERT", raising=False)
    assert trend_alert.trend_alert_enabled() is False
    assert trend_alert.start_trend_alert_watcher() is False


def test_first_run_records_baseline_without_alert():
    with _patch_ranking([TOP_ROW]):
        outcome = trend_alert.check_trend_takeover()
    assert outcome == {"netuid": 42, "sent": False, "baseline": True}
    state = trend_alert._read_state()
    assert state["last_top_netuid"] == 42
    assert state["last_top_name"] == "TestNet"


def test_takeover_sends_alert_and_persists(monkeypatch):
    monkeypatch.setenv("APP_BASE_URL", "https://example.test")
    trend_alert._write_state({"last_top_netuid": 41, "last_top_name": "OldNet"})
    p, sends = _patch_send()
    with _patch_ranking([TOP_ROW, PREV_ROW]), p:
        outcome = trend_alert.check_trend_takeover()
    assert outcome["sent"] is True
    chat_id, text = sends[0]
    assert chat_id == "@officialsubnetsummer"
    assert "New #1 Trending" in text
    assert "SN42 TestNet" in text
    assert "took over from SN41 OldNet" in text
    assert "2 mentions" in text
    assert "https://example.test/subnetsummer" in text
    assert trend_alert._read_state()["last_top_netuid"] == 42


def test_no_alert_when_top_unchanged():
    trend_alert._write_state({"last_top_netuid": 42, "last_top_name": "TestNet"})
    p, sends = _patch_send()
    with _patch_ranking([TOP_ROW]), p:
        outcome = trend_alert.check_trend_takeover()
    assert outcome is None
    assert sends == []


def test_send_failure_keeps_state_for_retry():
    trend_alert._write_state({"last_top_netuid": 41, "last_top_name": "OldNet"})
    p, sends = _patch_send(ok=False)
    with _patch_ranking([TOP_ROW]), p:
        outcome = trend_alert.check_trend_takeover()
    assert outcome == {"netuid": 42, "sent": False, "target": "@officialsubnetsummer"}
    assert len(sends) == 1
    assert trend_alert._read_state()["last_top_netuid"] == 41


def test_min_mentions_gate(monkeypatch):
    monkeypatch.setenv("TREND_ALERT_MIN_MENTIONS", "5")
    trend_alert._write_state({"last_top_netuid": 41, "last_top_name": "OldNet"})
    with _patch_ranking([dict(TOP_ROW, mentions=2)]):
        outcome = trend_alert.check_trend_takeover()
    assert outcome is None
    assert trend_alert._read_state()["last_top_netuid"] == 41


def test_alert_chat_id_precedence(monkeypatch):
    trend_alert._seen_chats.clear()
    trend_alert._seen_chats[-100200] = 1.0
    trend_alert._seen_chats[-100300] = 2.0
    assert trend_alert.alert_chat_id() == "-100300"
    monkeypatch.setenv("TELEGRAM_TREND_ALERT_CHAT", "-123")
    assert trend_alert.alert_chat_id() == "-123"
    monkeypatch.delenv("TELEGRAM_TREND_ALERT_CHAT")
    trend_alert._seen_chats.clear()
    monkeypatch.setenv("TELEGRAM_GROUP", "examplegroup")
    assert trend_alert.alert_chat_id() == "@examplegroup"


def test_record_seen_chat():
    trend_alert.record_seen_chat("oops")
    trend_alert.record_seen_chat(-999)
    assert -999 in trend_alert._seen_chats
