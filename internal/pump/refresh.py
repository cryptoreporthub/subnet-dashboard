"""Pump ladder freshness — scan when stale (prod web has BACKGROUND_ON_WEB=off)."""

from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

STALE_MINUTES = int(os.environ.get("PUMP_LADDER_STALE_MINUTES", "8"))
SCAN_COOLDOWN_SECONDS = int(os.environ.get("PUMP_LADDER_SCAN_COOLDOWN_SECONDS", "90"))

_lock = threading.Lock()
_last_scan_attempt = 0.0


def _background_scans_allowed() -> bool:
    """Skip daemon scans under pytest / Deploy Guard — they hang contract jobs."""
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return False
    flag = os.environ.get("DISABLE_BACKGROUND_SCANS", "").strip().lower()
    if flag in {"1", "true", "yes", "on"}:
        return False
    return True


def _parse_ts(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None


def ladder_age_minutes() -> Optional[float]:
    try:
        from internal.pump.state import load_state

        meta = load_state().get("meta") or {}
        last = _parse_ts(meta.get("last_scan_at"))
        if last is None:
            return None
        return max(0.0, (datetime.now(timezone.utc) - last).total_seconds() / 60.0)
    except Exception:
        return None


def _needs_scan(*, force: bool = False) -> bool:
    """True when ladder is missing/stale and cooldown allows a scan."""
    global _last_scan_attempt
    now_mono = time.monotonic()
    with _lock:
        if not force and (now_mono - _last_scan_attempt) < SCAN_COOLDOWN_SECONDS:
            return False
        try:
            from internal.pump.state import load_state

            meta = load_state().get("meta") or {}
            last = _parse_ts(meta.get("last_scan_at"))
            if last and not force:
                age = (datetime.now(timezone.utc) - last).total_seconds() / 60.0
                if age < STALE_MINUTES:
                    return False
        except Exception:
            pass
        _last_scan_attempt = now_mono
        return True


def _run_ladder_scan() -> bool:
    try:
        from internal.pump.state import scan_all_subnets

        result = scan_all_subnets()
        ok = bool(result.get("ok"))
        if ok:
            logger.info(
                "pump ladder scan ok scanned=%s transitions=%s",
                result.get("scanned"),
                len(result.get("transitions") or []),
            )
        else:
            logger.warning("pump ladder scan failed: %s", result.get("error"))
        return ok
    except Exception as exc:
        logger.warning("pump ladder scan exception: %s", exc)
        return False


def ensure_ladder_fresh(*, force: bool = False) -> bool:
    """Run ``scan_all_subnets`` when ladder is missing/stale. Returns True if scan ran."""
    if not _needs_scan(force=force):
        return False
    return _run_ladder_scan()


def kick_ladder_fresh(*, force: bool = False) -> Dict[str, Any]:
    """Fire-and-forget ladder refresh so /api/pump-alerts stays fast."""
    if not _background_scans_allowed():
        return {"status": "skipped", "reason": "background_disabled"}
    if not _needs_scan(force=force):
        return {"status": "skipped", "reason": "fresh_or_cooldown"}

    def _run() -> None:
        try:
            _run_ladder_scan()
        except Exception as exc:
            logger.debug("background ladder scan died: %s", exc)

    t = threading.Thread(target=_run, name="pump-ladder-scan", daemon=True)
    t.start()
    return {"status": "started", "thread": t.name}
