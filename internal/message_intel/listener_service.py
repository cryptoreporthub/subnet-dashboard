"""Background social listeners (Telegram) — Phase M."""

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

    api_id = os.environ.get("TELEGRAM_API_ID")
    api_hash = os.environ.get("TELEGRAM_API_HASH")
    if not (api_id and api_hash):
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
    return started


def stop_message_intel_listeners() -> None:
    global _listener
    if _listener is not None:
        try:
            _listener.stop()
        except Exception as exc:
            logger.warning("Telegram listener stop failed: %s", exc)
        _listener = None
