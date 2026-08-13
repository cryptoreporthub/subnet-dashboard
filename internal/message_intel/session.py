"""Telegram session resolution — file on volume or TELEGRAM_SESSION_STRING secret."""

from __future__ import annotations

import logging
import os
from typing import Any, Optional, Union

logger = logging.getLogger(__name__)

SessionArg = Union[str, Any]


def _session_base() -> str:
    return os.environ.get("TELEGRAM_SESSION_PATH", "data/telegram_listener").strip()


def _session_file_path() -> str:
    return f"{_session_base()}.session"


def _has_session_file() -> bool:
    return os.path.isfile(_session_file_path())


def _parse_string_session(raw: str) -> Any:
    from telethon.sessions import StringSession

    return StringSession(raw)


def string_session_parse_error(raw: Optional[str] = None) -> Optional[str]:
    """Return parse error for TELEGRAM_SESSION_STRING, or None when usable."""
    value = (raw if raw is not None else os.environ.get("TELEGRAM_SESSION_STRING", "")).strip()
    if not value:
        return None
    try:
        _parse_string_session(value)
    except Exception as exc:
        return f"{type(exc).__name__}: {exc}"
    return None


def has_telegram_session() -> bool:
    if string_session_parse_error() is None and os.environ.get("TELEGRAM_SESSION_STRING", "").strip():
        return True
    return _has_session_file()


def telegram_session_mode() -> str:
    """How Telethon will authenticate — for honest status (no secrets)."""
    raw = os.environ.get("TELEGRAM_SESSION_STRING", "").strip()
    has_file = _has_session_file()
    if raw:
        if string_session_parse_error(raw) is None:
            if has_file:
                return "string+file"
            return "string"
        if has_file:
            return "string_invalid+file"
        return "string_invalid"
    if has_file:
        return "file"
    return "none"


def telegram_session_arg() -> SessionArg:
    """Telethon session: StringSession from env, else SQLite path base."""
    raw = os.environ.get("TELEGRAM_SESSION_STRING", "").strip()
    if raw:
        try:
            return _parse_string_session(raw)
        except Exception as exc:
            if _has_session_file():
                path = _session_base()
                logger.warning(
                    "TELEGRAM_SESSION_STRING invalid (%s) — using volume file %s",
                    exc,
                    path,
                )
                return path
            raise
    return _session_base()
