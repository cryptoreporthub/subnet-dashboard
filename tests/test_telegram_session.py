"""Telegram session resolution — StringSession vs volume file."""

from __future__ import annotations

import pytest

from internal.message_intel import session as tg_session


def test_string_session_parse_error_detects_invalid():
    assert tg_session.string_session_parse_error("not-a-valid-session") is not None


def test_telegram_session_arg_falls_back_to_file(tmp_path, monkeypatch):
    base = tmp_path / "telegram_listener"
    (tmp_path / "telegram_listener.session").write_text("stub", encoding="utf-8")
    monkeypatch.setenv("TELEGRAM_SESSION_PATH", str(base))
    monkeypatch.setenv("TELEGRAM_SESSION_STRING", "bad-padding!!!")
    arg = tg_session.telegram_session_arg()
    assert arg == str(base)
    assert tg_session.telegram_session_mode() == "string_invalid+file"


def test_telegram_session_arg_raises_without_file(monkeypatch):
    monkeypatch.delenv("TELEGRAM_SESSION_PATH", raising=False)
    monkeypatch.setenv("TELEGRAM_SESSION_STRING", "bad-padding!!!")
    with pytest.raises(Exception):
        tg_session.telegram_session_arg()


def test_has_session_true_when_file_only(tmp_path, monkeypatch):
    base = tmp_path / "telegram_listener"
    (tmp_path / "telegram_listener.session").write_text("stub", encoding="utf-8")
    monkeypatch.setenv("TELEGRAM_SESSION_PATH", str(base))
    monkeypatch.delenv("TELEGRAM_SESSION_STRING", raising=False)
    assert tg_session.has_telegram_session() is True
    assert tg_session.telegram_session_mode() == "file"
