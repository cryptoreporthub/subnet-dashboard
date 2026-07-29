"""Background social listeners (Telegram) — Phase M / §17.F6."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_listener: Any = None
_heartbeat_stop: Optional[Any] = None
_last_backfill_attempt: float = 0.0
_DEFAULT_HEARTBEAT = "data/.message_intel_listener"


def _heartbeat_path() -> str:
    return os.environ.get("MESSAGE_INTEL_LISTENER_HEARTBEAT", _DEFAULT_HEARTBEAT)


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


def _worker_heavy_enabled() -> bool:
    from internal.run_mode import worker_heavy_feeds_enabled

    return worker_heavy_feeds_enabled()


def _has_session_file() -> bool:
    from internal.message_intel.session import has_telegram_session

    return has_telegram_session()


def _touch_listener_heartbeat() -> None:
    path = _heartbeat_path()
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    payload = {
        "pid": os.getpid(),
        "ts": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh)


def _clear_listener_heartbeat() -> None:
    try:
        os.remove(_heartbeat_path())
    except FileNotFoundError:
        pass
    except Exception as exc:
        logger.debug("listener heartbeat clear failed: %s", exc)


def _listener_alive_cross_process(*, max_age_seconds: int = 120) -> bool:
    try:
        with open(_heartbeat_path(), "r", encoding="utf-8") as fh:
            raw = json.load(fh)
        if not isinstance(raw, dict) or not raw.get("ts"):
            return False
        ts = datetime.fromisoformat(str(raw["ts"]).replace("Z", "+00:00"))
        age = (datetime.now(timezone.utc) - ts.astimezone(timezone.utc)).total_seconds()
        return age <= max_age_seconds
    except Exception:
        return False


def _listener_running_local() -> bool:
    return _listener is not None and bool(getattr(_listener, "_running", True))


def _feed_stale_threshold_seconds() -> float:
    try:
        return float(os.environ.get("TELEGRAM_FEED_STALE_SECONDS", "7200"))
    except ValueError:
        return 7200.0


def _backfill_interval_seconds() -> float:
    try:
        return float(os.environ.get("TELEGRAM_BACKFILL_INTERVAL_SECONDS", "1800"))
    except ValueError:
        return 1800.0


def _feed_stale_fields() -> Dict[str, Any]:
    from internal.message_intel.store import live_stats

    stats = live_stats()
    age = stats.get("last_message_age_seconds")
    threshold = _feed_stale_threshold_seconds()
    stale = age is not None and float(age) > threshold
    out: Dict[str, Any] = {}
    if stats.get("last_message_at"):
        out["last_message_at"] = stats["last_message_at"]
    if age is not None:
        out["last_message_age_seconds"] = age
    out["feed_stale"] = stale
    return out


def _maybe_backfill_if_stale() -> None:
    """ponytail: periodic backfill when feed quiet — live handler misses disconnect gaps."""
    global _last_backfill_attempt
    import time

    now = time.time()
    if now - _last_backfill_attempt < _backfill_interval_seconds():
        return
    if _listener is None or not _listener_running_local():
        return
    stats = _feed_stale_fields()
    age = stats.get("last_message_age_seconds")
    threshold = _feed_stale_threshold_seconds()
    if age is not None and float(age) <= threshold:
        return
    _last_backfill_attempt = now
    ok = bool(_listener.trigger_backfill())
    logger.info(
        "telegram stale-feed backfill age=%s ok=%s",
        age if age is not None else "none",
        ok,
    )


def listener_status() -> Dict[str, Any]:
    """Honest listener health for APIs — no secrets, no fake 'live' without creds."""
    from internal.data_volume import needs_worker_volume_proxy

    if needs_worker_volume_proxy():
        try:
            from internal.worker_proxy import fetch_worker_json_sync

            remote = fetch_worker_json_sync("/api/message-intel/status")
            listener = remote.get("listener")
            if isinstance(listener, dict):
                return listener
        except Exception as exc:
            logger.debug("worker listener status proxy failed: %s", exc)

    enabled = _listener_enabled()
    has_creds = _has_telegram_creds()
    telethon = _telethon_available()
    worker_heavy = _worker_heavy_enabled()
    has_session = _has_session_file()
    running = _listener_running_local() or _listener_alive_cross_process()
    hint = None

    if running:
        reason = "running"
    elif not enabled:
        reason = "disabled"
        hint = "Set MESSAGE_INTEL_LISTENER=auto after session bootstrap"
    elif not has_creds:
        reason = "missing_telegram_creds"
        hint = "Set TELEGRAM_API_ID and TELEGRAM_API_HASH (my.telegram.org)"
    elif not telethon:
        reason = "telethon_unavailable"
        hint = "Install telethon>=1.33.0 in the runtime image"
    elif not has_session:
        reason = "missing_session"
        hint = (
            "Run scripts/bootstrap_telegram_session.py locally, then set "
            "TELEGRAM_SESSION_STRING in Fly secrets (or save .session on the volume)"
        )
    else:
        reason = "idle_not_started"
        hint = "Listener should start on next worker boot; check fly logs for Telegram errors"

    out = {
        "enabled": enabled,
        "has_creds": has_creds,
        "telethon_available": telethon,
        "worker_heavy": worker_heavy,
        "has_session": has_session,
        "running": running,
        "reason": reason,
        "live": bool(running and has_creds),
        "monitored_group": os.environ.get("TELEGRAM_GROUP", "OfficialSubnetSummer"),
    }
    if _listener is not None:
        title = getattr(_listener, "group_title", None)
        if title:
            out["group_title"] = title
        out["group_connected"] = bool(getattr(_listener, "group_connected", False))
    if hint:
        out["hint"] = hint
    out.update(_feed_stale_fields())
    return out


def _on_telegram_message(normalized: Dict[str, Any]) -> None:
    from internal.message_intel.engine import ingest_message

    try:
        ingest_message(normalized, snapshot_price=True)
        _touch_listener_heartbeat()
    except Exception as exc:
        logger.warning("Telegram ingest failed: %s", exc)


def _start_heartbeat_loop() -> None:
    """Keep cross-process status fresh while the listener thread is alive."""
    global _heartbeat_stop
    import threading

    if _heartbeat_stop is not None:
        return
    stop = threading.Event()
    _heartbeat_stop = stop

    def _loop() -> None:
        while not stop.wait(45):
            if not _listener_running_local():
                break
            try:
                _touch_listener_heartbeat()
                _maybe_backfill_if_stale()
            except Exception as exc:
                logger.debug("listener heartbeat refresh failed: %s", exc)

    threading.Thread(target=_loop, daemon=True, name="mi-listener-heartbeat").start()


def _stop_heartbeat_loop() -> None:
    global _heartbeat_stop
    if _heartbeat_stop is not None:
        _heartbeat_stop.set()
        _heartbeat_stop = None


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

    from internal.message_intel.session import telegram_session_arg

    _listener = TelegramListener(
        on_message=_on_telegram_message,
        forward_to_ingest=False,
        session=telegram_session_arg(),
    )
    started = _listener.start()
    if started:
        _touch_listener_heartbeat()
        _start_heartbeat_loop()
        logger.info("Telegram message-intel listener started")
    else:
        _listener = None
    return started


def stop_message_intel_listeners() -> None:
    global _listener
    _stop_heartbeat_loop()
    if _listener is not None:
        try:
            _listener.stop()
        except Exception as exc:
            logger.warning("Telegram listener stop failed: %s", exc)
        _listener = None
    _clear_listener_heartbeat()
