"""Trending #1 takeover alert — pushes a Telegram note when a new subnet takes
over the top trending slot (SS-TG follow-on to the W6 summary bot)."""

from __future__ import annotations

import html
import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_TREND_THREAD: Optional[threading.Thread] = None
_TREND_STOP = threading.Event()
STATE_PATH = os.environ.get("TREND_STATE_PATH", "data/trend_state.json")

# Chats the summary bot has seen traffic from — fallback push targets.
_seen_chats: Dict[int, float] = {}
_seen_lock = threading.Lock()

_ENABLED = frozenset({"1", "true", "yes", "on"})


def trend_alert_enabled() -> bool:
    from internal.run_mode import stage2_hop_mode

    if stage2_hop_mode():
        return False
    return os.environ.get("TELEGRAM_TREND_ALERT", "off").strip().lower() in _ENABLED


def alert_chat_id() -> Optional[str]:
    """Resolve the push target: env override -> last active seen chat -> ingest group."""
    raw = os.environ.get("TELEGRAM_TREND_ALERT_CHAT", "").strip()
    if raw:
        return raw
    with _seen_lock:
        if _seen_chats:
            chat_id = max(_seen_chats.items(), key=lambda kv: kv[1])[0]
            return str(chat_id)
    group = os.environ.get("TELEGRAM_GROUP", "officialsubnetsummer").strip()
    return f"@{group.lstrip('@')}" if group else None


def record_seen_chat(chat_id: int) -> None:
    """Remember a chat the summary bot has seen traffic from (fallback target)."""
    try:
        with _seen_lock:
            _seen_chats[int(chat_id)] = time.time()
    except (TypeError, ValueError):
        pass


def _read_state() -> Dict[str, Any]:
    try:
        raw = Path(STATE_PATH).read_text(encoding="utf-8")
        data = json.loads(raw)
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
        logger.warning("trend takeover state write failed: %s", exc)


def _baseline_state(top: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "last_top_netuid": int(top.get("netuid") or 0),
        "last_top_name": str(top.get("name") or ""),
        "updated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }


def format_takeover_message(top: Dict[str, Any], previous: Optional[Dict[str, Any]]) -> str:
    """Telegram HTML note for a trending #1 takeover."""
    from internal.message_intel.summary_bot import _desk_url

    netuid = top.get("netuid")
    name = str(top.get("name") or "").strip()
    label = f"SN{netuid} {name}".strip()
    lines = [f"🚨 <b>New #1 Trending — {html.escape(label)}</b>"]
    if previous is not None:
        prev_label = f"SN{previous.get('netuid')} {previous.get('name') or ''}".strip()
        lines.append(f"(took over from {html.escape(prev_label)})")
    lines.append("")

    mentions = int(top.get("mentions") or 0)
    mention_word = "mention" if mentions == 1 else "mentions"
    bits = [f"{mentions} {mention_word}", f"power {top.get('chatter_power', 0)}"]
    lines.append(" · ".join(bits))
    why = str(top.get("why") or "").strip()
    if why:
        lines.append(f"<i>{html.escape(why, quote=False)}</i>")
    lines.append("")
    lines.append(f'<a href="{_desk_url()}">Open the Subnet Summers desk</a>')
    return "\n".join(lines)


def check_trend_takeover(*, db=None) -> Optional[Dict[str, Any]]:
    """One pass: rank trending, alert on a #1 change, persist state.

    Returns an outcome dict ({netuid, sent, ...}) or None when nothing happened.
    """
    from internal.message_intel.rollup import build_trending_subnets
    from internal.message_intel.summary_bot import _registry_subnet_names

    try:
        rank_hours = max(1, int(os.environ.get("TREND_ALERT_RANK_HOURS", "24")))
    except ValueError:
        rank_hours = 24
    try:
        min_mentions = max(1, int(os.environ.get("TREND_ALERT_MIN_MENTIONS", "1")))
    except ValueError:
        min_mentions = 1

    try:
        items = build_trending_subnets(
            limit=2,
            rank_hours=rank_hours,
            window_hours=24,
            registry_names=_registry_subnet_names(),
            db=db,
        )
    except Exception as exc:
        logger.warning("trend takeover ranking failed: %s", exc)
        return None

    if not items:
        return None
    top = items[0]
    try:
        top_netuid = int(top.get("netuid"))
    except (TypeError, ValueError):
        return None
    if int(top.get("mentions") or 0) < min_mentions:
        return None

    state = _read_state()
    raw_last = state.get("last_top_netuid")
    if raw_last is None:
        # First observation: record baseline, no alert.
        _write_state(_baseline_state(top))
        return {"netuid": top_netuid, "sent": False, "baseline": True}

    try:
        last_netuid = int(raw_last)
    except (TypeError, ValueError):
        last_netuid = None
    if last_netuid == top_netuid:
        return None

    previous = {"netuid": last_netuid, "name": str(state.get("last_top_name") or "")}
    message = format_takeover_message(top, previous)

    target = alert_chat_id()
    sent = False
    if target:
        from internal.message_intel.summary_bot import send_message

        chat: Any = target
        if str(target).lstrip("-").isdigit():
            chat = int(target)
        resp = send_message(chat, message, link_preview=False)
        sent = bool(resp.get("ok"))
        if not sent:
            logger.warning("trend takeover send failed: %s", resp.get("error") or resp)

    if not sent:
        # Keep prior state so the next tick retries the same takeover.
        return {"netuid": top_netuid, "sent": False, "target": target}

    _write_state(_baseline_state(top))
    return {"netuid": top_netuid, "sent": True, "target": target}


def _trend_loop() -> None:
    try:
        interval = max(60, int(os.environ.get("TREND_ALERT_INTERVAL_SECONDS", "600")))
    except ValueError:
        interval = 600
    logger.info("trend takeover watcher started (interval=%ss)", interval)
    while not _TREND_STOP.is_set():
        try:
            check_trend_takeover()
        except Exception as exc:
            logger.warning("trend takeover tick failed: %s", exc)
        _TREND_STOP.wait(interval)


def start_trend_alert_watcher() -> bool:
    """Start the periodic takeover check when env-gated."""
    global _TREND_THREAD
    if not trend_alert_enabled():
        logger.info("trend takeover alert disabled (TELEGRAM_TREND_ALERT=off)")
        return False
    if _TREND_THREAD is not None and _TREND_THREAD.is_alive():
        return True

    _TREND_STOP.clear()
    _TREND_THREAD = threading.Thread(target=_trend_loop, daemon=True, name="trend-takeover-alert")
    _TREND_THREAD.start()
    return True


def stop_trend_alert_watcher() -> None:
    global _TREND_THREAD
    _TREND_STOP.set()
    if _TREND_THREAD is not None:
        _TREND_THREAD.join(timeout=5)
        _TREND_THREAD = None
    _TREND_STOP.clear()
