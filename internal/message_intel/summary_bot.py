"""Telegram Bot API /summary handler — SS-TG W6 (env-gated; not the Telethon listener)."""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import urllib.error
import urllib.request
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_POLL_THREAD: Optional[threading.Thread] = None
_STOP = threading.Event()
_RATE_LIMIT_SECONDS = 300
_last_summary_at: Dict[int, float] = {}
_RUNNING = False

_ENABLED = frozenset({"1", "true", "yes", "on"})


def summary_bot_enabled() -> bool:
    return os.environ.get("TELEGRAM_SUMMARY_BOT", "off").strip().lower() in _ENABLED


def _bot_token() -> str:
    return os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()


def _desk_url() -> str:
    base = os.environ.get("APP_BASE_URL", "").strip().rstrip("/")
    if base:
        return f"{base}/#section-message-intel"
    return "https://subnet-dashboard.fly.dev/#section-message-intel"


def _telegram_api(method: str, payload: Dict[str, Any], *, timeout: float = 35.0) -> Dict[str, Any]:
    token = _bot_token()
    if not token:
        return {"ok": False, "error": "missing_token"}
    url = f"https://api.telegram.org/bot{token}/{method}"
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", "User-Agent": "subnet-dashboard-summary-bot"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {"ok": True}
    except urllib.error.HTTPError as exc:
        try:
            detail = exc.read().decode("utf-8")
        except Exception:
            detail = str(exc)
        return {"ok": False, "status": exc.code, "error": detail}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _registry_subnet_names() -> Dict[int, str]:
    from internal.message_intel.engine import _registry_subnet_names

    return _registry_subnet_names()


def format_summary_message(summary: Dict[str, Any], *, desk_url: Optional[str] = None) -> str:
    """Render build_24h_summary dict as Telegram HTML."""
    desk = desk_url or _desk_url()
    if not summary.get("ready"):
        count = int(summary.get("message_count") or 0)
        need = int(summary.get("min_messages") or 10)
        return (
            f"<b>Subnet Summers — 24h pulse</b>\n\n"
            f"Not enough chatter yet ({count}/{need} messages in 24h).\n"
            f"Check back when the group is active.\n\n"
            f'<a href="{desk}">Open the Subnet Summers desk</a>'
        )

    lines = [
        "<b>Subnet Summers — 24h pulse</b>",
        "",
        f"Messages: {summary.get('message_count', 0)} · "
        f"High conviction: {summary.get('high_conviction_count', 0)}",
    ]
    top = summary.get("top_subnets") or []
    if top:
        lines.append("")
        lines.append("<b>Top subnets</b>")
        for row in top[:5]:
            name = row.get("name") or f"SN{row.get('netuid')}"
            lines.append(f"• SN{row.get('netuid')} {name} ({row.get('mentions', 0)} mentions)")

    movers = [m for m in (summary.get("movers") or []) if int(m.get("change") or 0) != 0][:3]
    if movers:
        lines.append("")
        lines.append("<b>Movers</b> (24h vs prior 24h)")
        for row in movers:
            delta = int(row.get("change") or 0)
            arrow = "↑" if delta > 0 else "↓"
            name = row.get("name") or f"SN{row.get('netuid')}"
            lines.append(f"• SN{row.get('netuid')} {name} {arrow}{abs(delta)}")

    pulse = summary.get("group_pulse") or {}
    if pulse.get("group"):
        lines.append("")
        lines.append(
            f"<b>Group pulse:</b> {pulse['group']} ({pulse.get('top_group_messages', pulse.get('messages', 0))} msgs, "
            f"{pulse.get('groups_active', 1)} active)"
        )
    elif pulse.get("messages"):
        lines.append("")
        lines.append(
            f"<b>Group pulse:</b> {pulse.get('messages', 0)} msgs · "
            f"{pulse.get('sentiment', 'Cautious')} · avg conv {pulse.get('avg_conviction', 0)}%"
        )

    lines.extend(["", f'<a href="{desk}">Open the Subnet Summers desk</a>'])
    return "\n".join(lines)


def build_summary_text(*, db=None) -> str:
    from internal.message_intel.rollup import build_24h_summary

    summary = build_24h_summary(registry_names=_registry_subnet_names(), db=db)
    return format_summary_message(summary)


def _rate_limit_reply(chat_id: int) -> Optional[str]:
    now = time.monotonic()
    last = _last_summary_at.get(chat_id, 0.0)
    elapsed = now - last
    if elapsed < _RATE_LIMIT_SECONDS:
        remaining = int(_RATE_LIMIT_SECONDS - elapsed)
        mins = max(1, (remaining + 59) // 60)
        return f"Rate limited — one /summary every 5 minutes. Try again in ~{mins} min."
    _last_summary_at[chat_id] = now
    return None


def handle_summary_command(chat_id: int, *, db=None) -> tuple[str, bool]:
    """Return (text, rate_limited)."""
    limited = _rate_limit_reply(chat_id)
    if limited:
        return limited, True
    return build_summary_text(db=db), False


def send_message(chat_id: int, text: str, *, parse_mode: str = "HTML") -> Dict[str, Any]:
    return _telegram_api(
        "sendMessage",
        {"chat_id": chat_id, "text": text, "parse_mode": parse_mode, "disable_web_page_preview": False},
    )


def _process_update(update: Dict[str, Any]) -> None:
    message = update.get("message") or update.get("edited_message")
    if not isinstance(message, dict):
        return
    text = str(message.get("text") or "").strip()
    if not text or not text.split()[0].startswith("/summary"):
        return
    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    if chat_id is None:
        return
    try:
        chat_id = int(chat_id)
    except (TypeError, ValueError):
        return

    reply, _limited = handle_summary_command(chat_id)
    resp = send_message(chat_id, reply)
    if not resp.get("ok"):
        logger.warning("summary bot send failed chat=%s: %s", chat_id, resp.get("error") or resp)


def _poll_loop() -> None:
    global _RUNNING
    offset = 0
    _RUNNING = True
    logger.info("Telegram summary bot polling started")
    while not _STOP.is_set():
        resp = _telegram_api(
            "getUpdates",
            {"offset": offset, "timeout": 25, "allowed_updates": ["message", "edited_message"]},
            timeout=35.0,
        )
        if not resp.get("ok"):
            logger.warning("summary bot getUpdates failed: %s", resp.get("error") or resp)
            if _STOP.wait(5):
                break
            continue
        for update in resp.get("result") or []:
            if not isinstance(update, dict):
                continue
            offset = int(update.get("update_id", offset)) + 1
            try:
                _process_update(update)
            except Exception as exc:
                logger.warning("summary bot update failed: %s", exc)
    _RUNNING = False
    logger.info("Telegram summary bot polling stopped")


def summary_bot_running() -> bool:
    return _RUNNING and _POLL_THREAD is not None and _POLL_THREAD.is_alive()


def start_summary_bot() -> bool:
    """Start Bot API long-poll loop when env-gated and token present."""
    global _POLL_THREAD
    if not summary_bot_enabled():
        logger.info("Telegram summary bot disabled (TELEGRAM_SUMMARY_BOT=off)")
        return False
    if not _bot_token():
        logger.info("Telegram summary bot skipped — TELEGRAM_BOT_TOKEN not set")
        return False
    if _POLL_THREAD is not None and _POLL_THREAD.is_alive():
        return True

    _STOP.clear()
    _POLL_THREAD = threading.Thread(target=_poll_loop, daemon=True, name="telegram-summary-bot")
    _POLL_THREAD.start()
    return True


def stop_summary_bot() -> None:
    global _POLL_THREAD
    _STOP.set()
    if _POLL_THREAD is not None:
        _POLL_THREAD.join(timeout=8)
        _POLL_THREAD = None
    _STOP.clear()
