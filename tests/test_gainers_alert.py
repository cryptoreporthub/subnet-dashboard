"""Gainers push alert: interval gating, honest-empty skip, dedup."""

from __future__ import annotations

import json

import pytest

from internal.message_intel import gainers_alert as ga

MSG = "<b>Top 5 gainers — last 24h</b>"
NO_DATA = "No 24h price-change data available right now — try again shortly."
T0 = 1_800_000_000.0


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(ga, "STATE_PATH", str(tmp_path / "state.json"))
    # keep every test off the network; tests override when they care
    from internal.message_intel import summary_bot as sb
    from internal.message_intel import stake_alert as sa

    monkeypatch.setattr(sb, "_format_gainers_reply", lambda db=None: MSG)
    monkeypatch.setattr(sb, "send_message", lambda chat, msg, **kw: {"ok": True})
    monkeypatch.setattr(sa, "alert_chat_id", lambda: "-100")
    yield


def _dt(epoch):
    from datetime import datetime, timezone

    return datetime.fromtimestamp(epoch, tz=timezone.utc)


def test_sends_on_first_tick_and_records_state():
    out = ga.check_gainers_alert(now=_dt(T0))
    assert out == {"sent": True, "target": "-100"}
    state = json.load(open(ga.STATE_PATH))
    assert state["last_sent_at_epoch"] == T0
    assert state["last_message"] == MSG


def test_quiet_inside_interval():
    ga.check_gainers_alert(now=_dt(T0))
    assert ga.check_gainers_alert(now=_dt(T0 + 3600)) is None


def test_no_resend_of_unchanged_list(monkeypatch):
    from internal.message_intel import summary_bot as sb

    sent = []
    monkeypatch.setattr(sb, "send_message", lambda chat, msg, **kw: sent.append(msg) or {"ok": True})
    ga.check_gainers_alert(now=_dt(T0))
    # one interval later, identical top-5 — timestamp refreshed, no duplicate push
    later = _dt(T0 + 90_000)
    assert ga.check_gainers_alert(now=later) is None
    assert sent == [MSG]
    assert json.load(open(ga.STATE_PATH))["last_sent_at_epoch"] == later.timestamp()


def test_resends_when_list_changes(monkeypatch):
    from internal.message_intel import summary_bot as sb

    sent = []
    monkeypatch.setattr(sb, "send_message", lambda chat, msg, **kw: sent.append(msg) or {"ok": True})
    ga.check_gainers_alert(now=_dt(T0))
    monkeypatch.setattr(sb, "_format_gainers_reply", lambda db=None: MSG + " (changed)")
    assert ga.check_gainers_alert(now=_dt(T0 + 90_000)) == {"sent": True, "target": "-100"}
    assert len(sent) == 2


def test_honest_empty_skips_without_scheduling(monkeypatch):
    from internal.message_intel import summary_bot as sb

    monkeypatch.setattr(sb, "_format_gainers_reply", lambda db=None: NO_DATA)
    # empty data must stay due — no state file is ever written
    assert ga.check_gainers_alert(now=_dt(T0 + 90_000)) is None
    import pathlib

    assert not pathlib.Path(ga.STATE_PATH).exists()


def test_watcher_env_gated(monkeypatch):
    monkeypatch.delenv("TELEGRAM_GAINERS_ALERT", raising=False)
    assert ga.start_gainers_alert_watcher() is False
    monkeypatch.setenv("TELEGRAM_GAINERS_ALERT", "on")
    assert ga.start_gainers_alert_watcher() is True
    ga.stop_gainers_alert_watcher()
