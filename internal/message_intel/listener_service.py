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
    payload: Dict[str, Any] = {
        "pid": os.getpid(),
        "ts": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    if _listener is not None:
        payload["group_connected"] = bool(getattr(_listener, "group_connected", False))
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh)


def _clear_listener_heartbeat() -> None:
    try:
        os.remove(_heartbeat_path())
    except FileNotFoundError:
        pass
    except Exception as exc:
        logger.debug("listener heartbeat clear failed: %s", exc)


def _heartbeat_group_connected() -> bool:
    try:
        with open(_heartbeat_path(), "r", encoding="utf-8") as fh:
            raw = json.load(fh)
        if isinstance(raw, dict) and "group_connected" in raw:
            return bool(raw.get("group_connected"))
    except Exception:
        pass
    return False


def _heartbeat_age_seconds() -> Optional[float]:
    try:
        with open(_heartbeat_path(), "r", encoding="utf-8") as fh:
            raw = json.load(fh)
        if not isinstance(raw, dict) or not raw.get("ts"):
            return None
        ts = datetime.fromisoformat(str(raw["ts"]).replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - ts.astimezone(timezone.utc)).total_seconds()
    except Exception:
        return None


def _listener_alive_cross_process(*, max_age_seconds: int = 120) -> bool:
    age = _heartbeat_age_seconds()
    return age is not None and age <= max_age_seconds


def _listener_running_local() -> bool:
    if _listener is None or not getattr(_listener, "_running", False):
        return False
    thread = getattr(_listener, "_thread", None)
    return thread is None or thread.is_alive()


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

    group_connected = False
    if _listener is not None:
        group_connected = bool(getattr(_listener, "group_connected", False))
    elif running and _listener_alive_cross_process():
        group_connected = _heartbeat_group_connected()

    if running:
        reason = "group_not_connected" if has_creds and not group_connected else "running"
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
    elif os.path.isfile(_heartbeat_path()) and not running:
        reason = "listener_stopped"
        hint = "Listener thread stopped — watchdog will restart it automatically"
    else:
        reason = "idle_not_started"
        hint = "Listener should start on next worker boot; check fly logs for Telegram errors"

    try:
        from internal.message_intel.store import live_stats

        total_messages = int((live_stats() or {}).get("total_messages") or 0)
    except Exception:
        total_messages = 0
    desk_ready = total_messages > 5

    from internal.message_intel.session import telegram_session_mode

    out = {
        "enabled": enabled,
        "has_creds": has_creds,
        "telethon_available": telethon,
        "worker_heavy": worker_heavy,
        "has_session": has_session,
        "running": running,
        "reason": reason,
        "live": bool(running and has_creds and group_connected),
        "desk_ready": desk_ready,
        "monitored_group": os.environ.get("TELEGRAM_GROUP", "officialsubnetsummer"),
        "group_connected": group_connected,
        "session_mode": telegram_session_mode(),
    }
    if _listener is not None:
        title = getattr(_listener, "group_title", None)
        if title:
            out["group_title"] = title
        mode = getattr(_listener, "session_mode", None)
        if mode:
            out["active_session_mode"] = mode
        label = getattr(_listener, "telegram_user_label", None)
        if label:
            out["telegram_user"] = label
        err = getattr(_listener, "entity_resolve_error", None)
        if err:
            out["entity_resolve_error"] = err
        attempts = getattr(_listener, "entity_resolve_attempts", None)
        if attempts:
            out["entity_resolve_attempts"] = list(attempts)[-8:]
    if not group_connected and running and has_creds:
        err = out.get("entity_resolve_error") or ""
        if "unauthorized" in err.lower():
            hint = (
                "Stale TELEGRAM_SESSION_STRING Fly secret — unset it to use volume .session "
                "or paste a fresh string from bootstrap_telegram_session.py"
            )
        out["hint"] = hint or "Listener thread up but group not resolved — check TELEGRAM_GROUP / TELEGRAM_GROUP_ID"
    elif hint:
        out["hint"] = hint
    out.update(_feed_stale_fields())
    feed_stale = bool(out.get("feed_stale"))
    is_live = bool(out.get("live")) and not feed_stale
    if is_live:
        out["display_mode"] = "live"
    elif out.get("reason") == "listener_stopped" or (
        running and has_creds and not group_connected
    ):
        out["display_mode"] = "reconnecting"
    elif desk_ready:
        out["display_mode"] = "archive"
    else:
        out["display_mode"] = "warming"
    # Never advertise live when feed is stale (honest status rail).
    out["live"] = is_live
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
        while True:
            if not _listener_running_local():
                break
            try:
                _touch_listener_heartbeat()
                _maybe_backfill_if_stale()
            except Exception as exc:
                logger.debug("listener heartbeat refresh failed: %s", exc)
            if _heartbeat_stop.wait(45):
                break

    threading.Thread(target=_loop, daemon=True, name="mi-listener-heartbeat").start()


def _stop_heartbeat_loop() -> None:
    global _heartbeat_stop
    if _heartbeat_stop is not None:
        _heartbeat_stop.set()
        _heartbeat_stop = None


def _reset_listener_if_dead() -> None:
    """Clear stale listener handle when the background thread exited."""
    global _listener
    if _listener is None:
        return
    if _listener_running_local():
        return
    logger.warning("Telegram listener thread stopped — clearing stale handle")
    try:
        _listener.stop()
    except Exception as exc:
        logger.debug("listener stop during reset failed: %s", exc)
    _listener = None
    _stop_heartbeat_loop()


def _listener_watchdog_interval_seconds() -> float:
    try:
        return float(os.environ.get("MESSAGE_INTEL_LISTENER_WATCHDOG_SECONDS", "300"))
    except ValueError:
        return 300.0


def _start_listener_watchdog() -> None:
    """Restart Telegram listener when its thread or cross-process heartbeat goes stale."""
    import threading
    import time

    def _loop() -> None:
        while True:
            time.sleep(_listener_watchdog_interval_seconds())
            if not _listener_enabled():
                continue
            if _listener_running_local() or _listener_alive_cross_process():
                if _listener_running_local():
                    _maybe_backfill_if_stale()
                continue
            if not _has_telegram_creds() or not _has_session_file():
                continue
            logger.info("message-intel listener watchdog: restarting listener")
            _reset_listener_if_dead()
            start_message_intel_listeners()

    threading.Thread(target=_loop, daemon=True, name="mi-listener-watchdog").start()


def start_message_intel_listeners() -> bool:
    """Start configured social listeners (Telegram when creds present)."""
    global _listener
    if not _listener_enabled():
        logger.info("Message-intel listeners disabled (MESSAGE_INTEL_LISTENER=off)")
        return False
    if _listener is not None:
        if _listener_running_local():
            return True
        _reset_listener_if_dead()

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
