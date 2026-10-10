"""Daily top-5 gainers push — same list as the /gainers command, proactively sent.

Env-gated watcher: ``TELEGRAM_GAINERS_ALERT=on``, send interval
``GAINERS_ALERT_INTERVAL_HOURS`` (default 24). Quietly skips ticks with no
price data (honest-empty is a command reply, not an alert).
"""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

STATE_PATH = os.environ.get("GAINERS_ALERT_STATE_PATH", "data/gainers_alert_state.json")
_ALERT_THREAD: Optional[threading.Thread] = None
_ALERT_STOP = threading.Event()


def gainers_alert_enabled() -> bool:
    from internal.run_mode import stage2_hop_mode

    if stage2_hop_mode():
        return False
    return os.environ.get("TELEGRAM_GAINERS_ALERT", "off").strip().lower() in (
        "1", "true", "yes", "on",
    )


def _read_state() -> Dict[str, Any]:
    try:
        data = json.loads(Path(STATE_PATH).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def _write_state(data: Dict[str, Any]) -> None:
    try:
        path = Path(STATE_PATH)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(path)
    except OSError as exc:
        logger.warning("gainers alert state write failed: %s", exc)


def _interval_seconds() -> int:
    try:
        hours = float(os.environ.get("GAINERS_ALERT_INTERVAL_HOURS", "24"))
    except ValueError:
        hours = 24.0
    return max(1, int(hours * 3600))


def check_gainers_alert(*, now: Optional[datetime] = None) -> Optional[Dict[str, Any]]:
    """One pass: due? fetch top-5, skip if unchanged, send to the alert chat."""
    from internal.message_intel.summary_bot import _format_gainers_reply, send_message

    now = now or datetime.now(timezone.utc)
    state = _read_state()
    last_sent = state.get("last_sent_at_epoch", 0)
    if now.timestamp() - last_sent < _interval_seconds():
        return None

    message = _format_gainers_reply()
    if "No 24h price-change data" in message:
        logger.info("gainers alert skipped: no price data")
        return None
    if state.get("last_message") == message:
        _write_state({**state, "last_sent_at_epoch": now.timestamp()})
        return None

    from internal.message_intel.stake_alert import alert_chat_id

    target = alert_chat_id()
    if not target:
        logger.warning("gainers alert: no alert chat configured")
        return None
    chat: Any = int(target) if str(target).lstrip("-").isdigit() else target
    resp = send_message(chat, message, link_preview=False)
    sent = bool(resp.get("ok"))
    if not sent:
        logger.warning("gainers alert send failed: %s", resp.get("error") or resp)
        return {"sent": False, "target": target}
    _write_state(
        {**state, "last_sent_at_epoch": now.timestamp(), "last_message": message}
    )
    return {"sent": True, "target": target}


def _alert_loop() -> None:
    logger.info("gainers alert watcher started (interval=%ss)", _interval_seconds())
    while not _ALERT_STOP.is_set():
        try:
            check_gainers_alert()
        except Exception as exc:
            logger.warning("gainers alert tick failed: %s", exc)
        _ALERT_STOP.wait(3600)


def start_gainers_alert_watcher() -> bool:
    """Start the daily gainers push when env-gated."""
    global _ALERT_THREAD
    if not gainers_alert_enabled():
        logger.info("gainers alert disabled (TELEGRAM_GAINERS_ALERT=off)")
        return False
    if _ALERT_THREAD is not None and _ALERT_THREAD.is_alive():
        return True

    _ALERT_STOP.clear()
    _ALERT_THREAD = threading.Thread(target=_alert_loop, daemon=True, name="gainers-alert")
    _ALERT_THREAD.start()
    return True


def stop_gainers_alert_watcher() -> None:
    global _ALERT_THREAD
    _ALERT_STOP.set()
    if _ALERT_THREAD is not None:
        _ALERT_THREAD.join(timeout=5)
        _ALERT_THREAD = None
    _ALERT_STOP.clear()
