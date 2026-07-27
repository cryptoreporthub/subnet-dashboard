"""Telegram session resolution — file on volume or TELEGRAM_SESSION_STRING secret."""

from __future__ import annotations

import os
from typing import Any, Union

SessionArg = Union[str, Any]


def _session_base() -> str:
    return os.environ.get("TELEGRAM_SESSION_PATH", "data/telegram_listener").strip()


def has_telegram_session() -> bool:
    raw = os.environ.get("TELEGRAM_SESSION_STRING", "").strip()
    if raw:
        return True
    return os.path.isfile(f"{_session_base()}.session")


def telegram_session_arg() -> SessionArg:
    """Telethon session: StringSession from env, else SQLite path base."""
    raw = os.environ.get("TELEGRAM_SESSION_STRING", "").strip()
    if raw:
        from telethon.sessions import StringSession

        return StringSession(raw)
    return _session_base()
