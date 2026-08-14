"""SS-TG W6 — Telegram Bot API /summary command (env-gated)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from internal.message_intel import summary_bot


@pytest.fixture(autouse=True)
def _reset_bot_state():
    summary_bot.stop_summary_bot()
    summary_bot._last_summary_at.clear()
    yield
    summary_bot.stop_summary_bot()
    summary_bot._last_summary_at.clear()


@pytest.fixture
def intel_env(tmp_path, monkeypatch):
    db_path = str(tmp_path / "message_intel.db")
    monkeypatch.setenv("MESSAGE_INTEL_DB", db_path)
    from internal.message_intel import store

    store.reset_db_cache()
    yield store.get_db(db_path)


def _seed_messages(db, count: int = 12, *, conviction: float = 65.0):
    base = datetime.now(timezone.utc)
    ids = []
    for i in range(count):
        mid, _ = db.save_message(
            {
                "source": "telegram",
                "group_name": "OfficialSubnetSummer",
                "author_name": f"user{i}",
                "content": f"SN{25 + (i % 3)} is moving",
                "timestamp": (base - timedelta(hours=i % 20)).isoformat(),
            }
        )
        db.save_analysis(
            mid,
            {"sentiment": "bullish", "entities": {"subnets": [f"SN{25 + (i % 3)}"]}, "influence_score": 0.4},
        )
        db.save_verdict(
            mid,
            {"verdict": "bullish", "conviction": conviction, "predicted_direction": "up"},
        )
        ids.append(mid)
    return ids


def test_summary_bot_disabled_by_default(monkeypatch):
    monkeypatch.delenv("TELEGRAM_SUMMARY_BOT", raising=False)
    assert summary_bot.summary_bot_enabled() is False
    assert summary_bot.start_summary_bot() is False


def test_summary_bot_requires_token(monkeypatch):
    monkeypatch.setenv("TELEGRAM_SUMMARY_BOT", "on")
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    assert summary_bot.start_summary_bot() is False


def test_build_24h_summary_honest_empty(intel_env):
    from internal.message_intel.rollup import build_24h_summary

    summary = build_24h_summary(db=intel_env)
    assert summary["ready"] is False
    assert summary["message_count"] == 0
    assert "empty_reason" in summary


def test_build_24h_summary_with_data(intel_env):
    from internal.message_intel.rollup import build_24h_summary

    _seed_messages(intel_env, count=12)
    summary = build_24h_summary(db=intel_env)
    assert summary["ready"] is True
    assert summary["message_count"] == 12
    assert summary["high_conviction_count"] == 12
    assert len(summary["top_subnets"]) >= 1
    assert summary["group_pulse"]["group"] == "OfficialSubnetSummer"
    assert summary["top_subnets"][0]["mention_context"] == "SN25 is moving"


def test_format_summary_includes_desk_link(monkeypatch, intel_env):
    monkeypatch.setenv("APP_BASE_URL", "https://example.test")
    from internal.message_intel.rollup import build_24h_summary

    _seed_messages(intel_env, count=12)
    text = summary_bot.format_summary_message(build_24h_summary(db=intel_env))
    assert "Subnet Summers — 24h pulse" in text
    assert "https://example.test/#section-message-intel" in text
    assert "Top subnets" in text


def test_format_summary_includes_what_mentions_are_about():
    text = summary_bot.format_summary_message(
        {
            "ready": True,
            "message_count": 12,
            "high_conviction_count": 4,
            "top_subnets": [
                {
                    "netuid": 7,
                    "name": "Allways",
                    "mentions": 3,
                    "mention_context": "Validators discussed a new release",
                }
            ],
        }
    )

    assert "SN7 Allways (3 mentions)" in text
    assert "Validators discussed a new release" in text


def test_rate_limit_per_chat(intel_env):
    chat_id = 999001
    first, limited1 = summary_bot.handle_summary_command(chat_id, db=intel_env)
    second, limited2 = summary_bot.handle_summary_command(chat_id, db=intel_env)
    assert limited1 is False
    assert limited2 is True
    assert "Rate limited" in second
    assert first != second


def test_process_update_ignores_non_summary():
    with patch.object(summary_bot, "send_message") as send:
        summary_bot._process_update({"message": {"chat": {"id": 1}, "text": "hello there"}})
        send.assert_not_called()


def test_process_update_handles_summary_command(intel_env):
    with patch.object(summary_bot, "send_message", return_value={"ok": True}) as send:
        summary_bot._process_update({"message": {"chat": {"id": 42}, "text": "/summary"}})
        send.assert_called_once()
        args, kwargs = send.call_args
        assert args[0] == 42
        assert "Subnet Summers" in args[1]


def test_start_command_lists_all_bot_commands():
    reply = summary_bot.handle_command("/start")

    assert "/summary" in reply
    assert "/trending" in reply
    assert "/track" in reply
    assert "/rank" in reply
    assert "/who" in reply
    assert "/alerts" in reply
    assert "/link" in reply


def test_alerts_command_without_toggle_lists_active_alerts(tmp_path, monkeypatch):
    monkeypatch.setenv("ALERTS_PATH", str(tmp_path / "alerts.json"))
    from internal.signals.alerts import AlertEngine

    engine = AlertEngine(alerts_path=str(tmp_path / "alerts.json"))
    engine.create_alert(
        {
            "alert_type": "manual",
            "message": "SN7 is warming",
            "severity": "info",
            "subnet_id": 7,
        }
    )

    with patch("internal.signals.alerts.AlertEngine", return_value=engine):
        reply = summary_bot.handle_command("/alerts")

    assert "SN7 is warming" in reply


def test_start_summary_bot_spawns_thread(monkeypatch):
    import threading

    monkeypatch.setenv("TELEGRAM_SUMMARY_BOT", "on")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:ABC")

    loop_ran = threading.Event()

    def fake_loop():
        loop_ran.set()

    with patch.object(summary_bot, "_poll_loop", side_effect=fake_loop):
        assert summary_bot.start_summary_bot() is True
        assert summary_bot.start_summary_bot() is True
        assert loop_ran.wait(timeout=2)
    summary_bot.stop_summary_bot()


def test_telegram_api_send(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:ABC")

    class _Resp:
        def read(self):
            return b'{"ok": true, "result": {"message_id": 1}}'

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    with patch("urllib.request.urlopen", return_value=_Resp()):
        resp = summary_bot.send_message(7, "hi")
    assert resp.get("ok") is True


def test_background_boot_wires_summary_bot():
    from pathlib import Path

    boot = Path("internal/background_boot.py").read_text(encoding="utf-8")
    assert "_maybe_start_summary_bot" in boot
    assert "telegram-summary-bot" in boot
    assert "stop_summary_bot" in boot


def test_fly_toml_summary_bot_on():
    from pathlib import Path

    fly = Path("fly.toml").read_text(encoding="utf-8")
    assert 'TELEGRAM_SUMMARY_BOT = "on"' in fly
