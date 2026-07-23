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
        cap = int(os.environ.get("WHALE_LEDGER_WARM_CAP", "5"))
    except ValueError:
        cap = 5
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
        if not meta:
            try:
                from fetchers.taomarketcap import get_all_subnets

                for s in get_all_subnets() or []:
                    nuid = s.get("netuid", s.get("id"))
                    if nuid is not None:
                        meta[int(nuid)] = s
            except Exception:
                pass

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
