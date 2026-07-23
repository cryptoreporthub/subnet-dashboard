"""Warm whale ledger for pump-desk netuids (capped, cooldown, no dup spam).

Prod ledger stays empty unless someone POSTs /api/whales/scan. Pump cards
need day-whale chips, so warm TaoStats delegations for active ladder names
when a netuid has no recent events.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_last_warm_attempt = 0.0


def _parse_iso(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None


def _netuids_missing_recent(
    events: Sequence[Dict[str, Any]],
    netuids: Sequence[int],
    *,
    hours: float = 24.0,
) -> List[int]:
    """Return netuids that have no ledger event in the window."""
    wanted = []
    seen = set()
    for n in netuids:
        try:
            ni = int(n)
        except (TypeError, ValueError):
            continue
        if ni < 1 or ni in seen:
            continue
        seen.add(ni)
        wanted.append(ni)
    if not wanted:
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(hours=float(hours))
    have = set()
    for ev in events or []:
        if not isinstance(ev, dict):
            continue
        try:
            nuid = int(ev.get("netuid"))
        except (TypeError, ValueError):
            continue
        if nuid not in seen:
            continue
        ts = _parse_iso(ev.get("timestamp"))
        if ts and ts >= cutoff:
            have.add(nuid)
    return [n for n in wanted if n not in have]


def ensure_whale_ledger_warm(
    netuids: Sequence[int],
    *,
    force: bool = False,
    subnet_meta_by_id: Optional[Dict[int, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Ingest TaoStats delegations for netuids lacking recent whale events.

    Caps live subnet scans (default 5) and cooldowns attempts so pump-alerts
    does not stampede the free-tier TaoStats budget.
    """
    global _last_warm_attempt

    try:
        from fetchers.taostats_client import is_available
    except Exception:
        return {"status": "skipped", "reason": "taostats_import"}

    if not is_available():
        return {"status": "skipped", "reason": "taostats_unavailable"}

    try:
        cooldown = int(os.environ.get("WHALE_LEDGER_WARM_COOLDOWN_SECONDS", "600"))
    except ValueError:
        cooldown = 600
    cooldown = max(30, min(cooldown, 3600))

    try:
        cap = int(os.environ.get("WHALE_LEDGER_WARM_CAP", "3"))
    except ValueError:
        cap = 3
    # Keep free-tier safe; share budget with pump TaoStats overlay.
    cap = max(1, min(cap, 5))

    now_mono = time.monotonic()
    with _lock:
        if not force and (now_mono - _last_warm_attempt) < cooldown:
            return {"status": "skipped", "reason": "cooldown"}
        _last_warm_attempt = now_mono

    try:
        from internal.whales.scanner import scan_netuids
        from internal.whales.service import WhaleIntelligenceService

        svc = WhaleIntelligenceService()
        missing = _netuids_missing_recent(
            svc.data.get("events") or [],
            netuids,
            hours=24.0,
        )
        if not missing:
            return {"status": "ok", "reason": "ledger_fresh", "scanned": 0, "ingested": 0}

        target = missing[:cap]
        meta = subnet_meta_by_id or {}
        # Skip TMC universe fetch here — meta is optional for ingest; avoids
        # blocking warm on a second external API.

        result = scan_netuids(target, subnet_meta_by_id=meta, service=svc)
        logger.info(
            "whale ledger warm scanned=%s ingested=%s missing=%s",
            result.get("scanned"),
            result.get("ingested"),
            len(missing),
        )
        return {
            "status": "ok",
            "scanned": result.get("scanned"),
            "ingested": result.get("ingested"),
            "missing": len(missing),
            "targets": target,
        }
    except Exception as exc:
        logger.warning("whale ledger warm failed: %s", exc)
        return {"status": "error", "error": str(exc)}


def kick_whale_ledger_warm(
    netuids: Sequence[int],
    *,
    force: bool = False,
) -> Dict[str, Any]:
    """Fire-and-forget warm so pump-alerts stays fast; chips appear on next hit."""
    global _last_warm_attempt

    try:
        cooldown = int(os.environ.get("WHALE_LEDGER_WARM_COOLDOWN_SECONDS", "600"))
    except ValueError:
        cooldown = 600
    cooldown = max(30, min(cooldown, 3600))

    now_mono = time.monotonic()
    with _lock:
        if not force and (now_mono - _last_warm_attempt) < cooldown:
            return {"status": "skipped", "reason": "cooldown"}
        # Claim the cooldown window so concurrent pump hits don't spawn a stampede.
        _last_warm_attempt = now_mono

    snapshot = [int(n) for n in netuids if n is not None]

    def _run() -> None:
        try:
            ensure_whale_ledger_warm(snapshot, force=True)
        except Exception as exc:
            logger.debug("background whale warm died: %s", exc)

    t = threading.Thread(target=_run, name="whale-ledger-warm", daemon=True)
    t.start()
    return {"status": "started", "thread": t.name}
