"""Telegram session mode reporting."""

from internal.message_intel.session import telegram_session_mode


def test_telegram_session_mode_string_and_file(monkeypatch, tmp_path):
    monkeypatch.setenv("TELEGRAM_SESSION_STRING", "1AgA...")
    monkeypatch.setenv("TELEGRAM_SESSION_PATH", str(tmp_path / "telegram_listener"))
    (tmp_path / "telegram_listener.session").write_text("x", encoding="utf-8")
    assert telegram_session_mode() == "string+file"


def test_telegram_session_mode_file_only(monkeypatch, tmp_path):
    monkeypatch.delenv("TELEGRAM_SESSION_STRING", raising=False)
    monkeypatch.setenv("TELEGRAM_SESSION_PATH", str(tmp_path / "telegram_listener"))
    (tmp_path / "telegram_listener.session").write_text("x", encoding="utf-8")
    assert telegram_session_mode() == "file"
