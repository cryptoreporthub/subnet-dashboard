"""Background social listeners (Telegram) — Phase M / §17.F6."""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_listener: Any = None


def _listener_enabled() -> bool:
    return os.environ.get("MESSAGE_INTEL_LISTENER", "auto").strip().lower() not in (
        "off",
        "false",
        "0",
        "no",
    )


def _telethon_available() -> bool:
    try:
        from message_intel.telegram_listener import HAS_TELETHON

        return bool(HAS_TELETHON)
    except Exception:
        return False


def _has_telegram_creds() -> bool:
    return bool(os.environ.get("TELEGRAM_API_ID") and os.environ.get("TELEGRAM_API_HASH"))


def listener_status() -> Dict[str, Any]:
    """Honest listener health for APIs — no secrets, no fake 'live' without creds."""
    enabled = _listener_enabled()
    has_creds = _has_telegram_creds()
    telethon = _telethon_available()
    running = _listener is not None and bool(getattr(_listener, "_running", True))

    if running:
        reason = "running"
    elif not enabled:
        reason = "disabled"
    elif not has_creds:
        reason = "missing_telegram_creds"
    elif not telethon:
        reason = "telethon_unavailable"
    else:
        reason = "idle_not_started"

    return {
        "enabled": enabled,
        "has_creds": has_creds,
        "telethon_available": telethon,
        "running": running,
        "reason": reason,
        "live": bool(running and has_creds),
    }


def _on_telegram_message(normalized: Dict[str, Any]) -> None:
    from internal.message_intel.engine import ingest_message

    try:
        ingest_message(normalized, snapshot_price=False)
    except Exception as exc:
        logger.warning("Telegram ingest failed: %s", exc)


def start_message_intel_listeners() -> bool:
    """Start configured social listeners (Telegram when creds present)."""
    global _listener
    if not _listener_enabled():
        logger.info("Message-intel listeners disabled (MESSAGE_INTEL_LISTENER=off)")
        return False
    if _listener is not None:
        return True

    if not _has_telegram_creds():
        logger.info("Telegram listener skipped — TELEGRAM_API_ID/HASH not set")
        return False

    try:
        from message_intel.telegram_listener import TelegramListener
    except ImportError as exc:
        logger.warning("Telegram listener unavailable: %s", exc)
        return False

    session = os.environ.get("TELEGRAM_SESSION_PATH", "data/telegram_listener")
    _listener = TelegramListener(
        on_message=_on_telegram_message,
        forward_to_ingest=False,
        session_name=session,
    )
    started = _listener.start()
    if started:
        logger.info("Telegram message-intel listener started")
    else:
        _listener = None
    return started


def stop_message_intel_listeners() -> None:
    global _listener
    if _listener is not None:
        try:
            _listener.stop()
        except Exception as exc:
            logger.warning("Telegram listener stop failed: %s", exc)
        _listener = None
