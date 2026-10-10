"""Background social listeners (Telegram) — Phase M / §17.F6."""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone
from typing import Any, Dict, Literal, Optional

BackfillOutcome = Literal["skipped_throttle", "not_ready", "failed", "ok"]

logger = logging.getLogger(__name__)

_listener: Any = None
_heartbeat_stop: Optional[Any] = None
_last_backfill_attempt: float = 0.0
_last_backfill_outcome: Optional[BackfillOutcome] = None
_last_backfill_outcome_at: float = 0.0
_backfill_lock = threading.Lock()
_listener_generation: int = 0
_forced_backfill_generation: int = -1
_forced_backfill_outcome: Optional[BackfillOutcome] = None
_forced_backfill_outcome_at: float = 0.0
_pending_start_backfill: bool = False
_feed_stale_watchdog_strikes: int = 0
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


def _feed_stale_restart_grace_seconds() -> float:
    """Age before feed_stale may trigger recovery (default 90m)."""
    try:
        return float(os.environ.get("TELEGRAM_FEED_STALE_RESTART_SECONDS", "5400"))
    except ValueError:
        return 5400.0


def _feed_stale_watchdog_strikes_required() -> int:
    try:
        return max(1, int(os.environ.get("TELEGRAM_FEED_STALE_WATCHDOG_STRIKES", "2")))
    except ValueError:
        return 2


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


def _gap_backfill_seconds() -> float:
    try:
        return float(os.environ.get("TELEGRAM_GAP_BACKFILL_SECONDS", "1800"))
    except ValueError:
        return 1800.0


def _listener_backfill_ready() -> bool:
    """Telethon client + resolved group entity required before gap backfill."""
    if _listener is None or not _listener_running_local():
        return False
    if not bool(getattr(_listener, "group_connected", False)):
        return False
    if getattr(_listener, "_monitor_entity", None) is None:
        return False
    if not getattr(_listener, "_loop", None) or not getattr(_listener, "_client", None):
        return False
    return True


def _clear_forced_backfill_cache() -> None:
    global _forced_backfill_generation, _forced_backfill_outcome, _forced_backfill_outcome_at
    _forced_backfill_generation = -1
    _forced_backfill_outcome = None
    _forced_backfill_outcome_at = 0.0


def _bump_listener_generation() -> int:
    global _listener_generation
    _listener_generation += 1
    _clear_forced_backfill_cache()
    return _listener_generation


def _listener_join_timeout_seconds() -> float:
    try:
        return float(os.environ.get("MESSAGE_INTEL_LISTENER_JOIN_SECONDS", "30"))
    except ValueError:
        return 30.0


def _attempt_listener_backfill_unlocked(*, force: bool = False) -> BackfillOutcome:
    """Run trigger_backfill when ready; throttle only applies to non-forced attempts."""
    global _last_backfill_attempt, _last_backfill_outcome, _last_backfill_outcome_at
    import time

    now = time.time()
    if not force and now - _last_backfill_attempt < _backfill_interval_seconds():
        return "skipped_throttle"
    if not _listener_backfill_ready():
        return "not_ready"

    stats = _feed_stale_fields()
    age = stats.get("last_message_age_seconds")
    threshold = _feed_stale_threshold_seconds()
    if age is not None and float(age) <= threshold and not force:
        return "skipped_throttle"

    _last_backfill_attempt = now
    ok = bool(_listener.trigger_backfill())
    outcome: BackfillOutcome = "ok" if ok else "failed"
    _last_backfill_outcome = outcome
    _last_backfill_outcome_at = now
    logger.info(
        "telegram backfill age=%s outcome=%s force=%s",
        age if age is not None else "none",
        outcome,
        force,
    )
    return outcome


def _attempt_listener_backfill(*, force: bool = False) -> BackfillOutcome:
    """Forced backfill: single-flight lock + coalesce ok/failed per listener generation."""
    global _forced_backfill_generation, _forced_backfill_outcome, _forced_backfill_outcome_at
    import time

    if not force:
        return _attempt_listener_backfill_unlocked(force=False)
    with _backfill_lock:
        now = time.time()
        gen = _listener_generation
        if (
            _forced_backfill_generation == gen
            and _forced_backfill_outcome in ("ok", "failed")
            and now - _forced_backfill_outcome_at < 45.0
        ):
            return _forced_backfill_outcome
        outcome = _attempt_listener_backfill_unlocked(force=True)
        _forced_backfill_generation = gen
        _forced_backfill_outcome = outcome
        _forced_backfill_outcome_at = time.time()
        return outcome


def _maybe_backfill_if_quiet() -> None:
    """Backfill when listener is up but the group has gone quiet (gap < stale threshold)."""
    if _listener is None or not _listener_running_local():
        return
    stats = _feed_stale_fields()
    age = stats.get("last_message_age_seconds")
    if age is None:
        return
    age_f = float(age)
    gap = _gap_backfill_seconds()
    stale = _feed_stale_threshold_seconds()
    if age_f < gap or age_f >= stale:
        return
    outcome = _attempt_listener_backfill(force=False)
    if outcome in ("ok", "failed"):
        logger.info("telegram quiet-gap backfill age=%.0fs outcome=%s", age_f, outcome)


def _maybe_backfill_if_stale(*, force: bool = False) -> bool:
    """ponytail: periodic backfill when feed quiet — live handler misses disconnect gaps."""
    outcome = _attempt_listener_backfill(force=force)
    return outcome == "ok"


def _maybe_backfill_on_listener_start() -> None:
    """Gap-fill after listener start once entity/loop are ready (deferred from start())."""
    global _pending_start_backfill

    if not _pending_start_backfill:
        return
    if _listener is None or not _listener_running_local():
        return
    if not _listener_backfill_ready():
        return
    stats = _feed_stale_fields()
    age = stats.get("last_message_age_seconds")
    if age is None:
        return
    if float(age) < _gap_backfill_seconds():
        _pending_start_backfill = False
        return
    outcome = _attempt_listener_backfill(force=True)
    if outcome == "not_ready":
        return
    _pending_start_backfill = False
    if outcome in ("ok", "failed"):
        logger.info(
            "telegram listener-start backfill age=%.0fs outcome=%s",
            float(age),
            outcome,
        )


def _maybe_restart_listener_if_feed_stale() -> None:
    """Restart Telethon when thread+heartbeat look fine but ingest is silent (zombie MTProto)."""
    global _feed_stale_watchdog_strikes

    if _listener is None or not _listener_running_local():
        _feed_stale_watchdog_strikes = 0
        return
    stats = _feed_stale_fields()
    if not stats.get("feed_stale"):
        _feed_stale_watchdog_strikes = 0
        return
    age = stats.get("last_message_age_seconds")
    if age is None or float(age) < _feed_stale_restart_grace_seconds():
        return

    outcome = _attempt_listener_backfill(force=True)
    if outcome in ("not_ready", "skipped_throttle"):
        return
    if outcome == "ok":
        fresh = _feed_stale_fields()
        if not fresh.get("feed_stale"):
            _feed_stale_watchdog_strikes = 0
        return

    _feed_stale_watchdog_strikes += 1
    need = _feed_stale_watchdog_strikes_required()
    logger.warning(
        "listener feed_stale recovery strike=%s/%s age=%.0fs outcome=%s",
        _feed_stale_watchdog_strikes,
        need,
        float(age),
        outcome,
    )
    if _feed_stale_watchdog_strikes < need:
        return

    logger.warning(
        "message-intel listener feed_stale watchdog: restarting listener (age=%.0fs)",
        float(age),
    )
    _feed_stale_watchdog_strikes = 0
    try:
        restart_message_intel_listeners()
    except Exception as exc:
        logger.warning("message-intel listener feed_stale watchdog: restart failed: %s", exc)


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

    from internal.message_intel.session import string_session_parse_error, telegram_session_mode

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
    session_err = string_session_parse_error()
    if session_err:
        out["session_string_error"] = session_err
        if _has_session_file() and reason == "idle_not_started":
            out["ops_hint"] = (
                "Stale TELEGRAM_SESSION_STRING Fly secret — unset it to use volume .session "
                "or paste a fresh string from bootstrap_telegram_session.py"
            )
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
            out["ops_hint"] = (
                "Stale TELEGRAM_SESSION_STRING Fly secret — unset it to use volume .session "
                "or paste a fresh string from bootstrap_telegram_session.py"
            )
            out["hint"] = "Reconnecting to Telegram — session may need refresh."
        else:
            out["ops_hint"] = (
                "Listener thread up but group not resolved — check TELEGRAM_GROUP / TELEGRAM_GROUP_ID"
            )
            out["hint"] = "Connecting to Subnet Summers — group link is still resolving."
    elif hint:
        out["hint"] = hint
        if any(tok in hint for tok in ("TELEGRAM_", "MESSAGE_INTEL_", "bootstrap_telegram")):
            out["ops_hint"] = hint
            if "TELEGRAM_SESSION_STRING" in hint:
                out["hint"] = "Telegram session needed — graded messages will appear when connected."
            elif "TELEGRAM_API" in hint:
                out["hint"] = "Telegram credentials needed — desk runs from archive until connected."
            elif "MESSAGE_INTEL_LISTENER" in hint:
                out["hint"] = "Listener warming up — archive desk loads first."
            elif "bootstrap_telegram" in hint:
                out["hint"] = "Telegram session needed — graded messages will appear when connected."
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
        stop = _heartbeat_stop  # captured: _stop_heartbeat_loop() nulls the global mid-loop
        while True:
            if not _listener_running_local():
                break
            try:
                _touch_listener_heartbeat()
                _maybe_backfill_on_listener_start()
                _maybe_backfill_if_quiet()
                _maybe_backfill_if_stale()
            except Exception as exc:
                logger.debug("listener heartbeat refresh failed: %s", exc)
            if stop is None or stop.wait(45):
                break

    threading.Thread(target=_loop, daemon=True, name="mi-listener-heartbeat").start()


def _stop_heartbeat_loop() -> None:
    global _heartbeat_stop
    if _heartbeat_stop is not None:
        _heartbeat_stop.set()
        _heartbeat_stop = None


def _retire_listener(join_timeout: Optional[float] = None) -> bool:
    """Stop listener, join its thread, and clear handles. Fail closed if join times out."""
    global _listener
    _stop_heartbeat_loop()
    old = _listener
    if old is None:
        _clear_listener_heartbeat()
        return True
    timeout = join_timeout if join_timeout is not None else _listener_join_timeout_seconds()
    try:
        old.stop()
    except Exception as exc:
        logger.warning("Telegram listener stop failed: %s", exc)
    thread = getattr(old, "_thread", None)
    if thread is not None and thread.is_alive():
        thread.join(timeout=timeout)
        if thread.is_alive():
            logger.error(
                "message-intel listener retire failed: thread still alive after %.0fs; "
                "restart aborted to avoid dual Telegram sessions (retry on next watchdog tick)",
                timeout,
            )
            return False
    _listener = None
    _clear_listener_heartbeat()
    return True


def restart_message_intel_listeners() -> bool:
    """Full stop/join/replace cycle for feed_stale watchdog and ops."""
    if not _retire_listener():
        return False
    return start_message_intel_listeners()


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
                    _maybe_backfill_if_quiet()
                    _maybe_backfill_if_stale()
                    _maybe_restart_listener_if_feed_stale()
                continue
            if not _has_telegram_creds() or not _has_session_file():
                continue
            logger.info("message-intel listener watchdog: restarting listener")
            try:
                _reset_listener_if_dead()
                start_message_intel_listeners()
            except Exception as exc:
                logger.warning("message-intel listener watchdog: restart failed: %s", exc)

    threading.Thread(target=_loop, daemon=True, name="mi-listener-watchdog").start()


def start_message_intel_listeners() -> bool:
    """Start configured social listeners (Telegram when creds present)."""
    global _listener, _pending_start_backfill
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

    try:
        session = telegram_session_arg()
    except Exception as exc:
        logger.warning("Telegram listener skipped — session init failed: %s", exc)
        return False

    _listener = TelegramListener(
        on_message=_on_telegram_message,
        forward_to_ingest=False,
        session=session,
    )
    started = _listener.start()
    if started:
        _bump_listener_generation()
        _touch_listener_heartbeat()
        _start_heartbeat_loop()
        _pending_start_backfill = True
        logger.info("Telegram message-intel listener started")
    else:
        _listener = None
    return started


def stop_message_intel_listeners() -> None:
    global _pending_start_backfill
    _pending_start_backfill = False
    _retire_listener()
