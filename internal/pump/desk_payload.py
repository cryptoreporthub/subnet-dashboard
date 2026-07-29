"""Pump desk payload — worker volume on split_v2 web, local ladder otherwise."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _local_pump_alerts_desk(
    subnets: Optional[List[Dict[str, Any]]],
    *,
    subnet_timeout: float,
) -> Dict[str, Any]:
    from internal.learning.pump_alert import build_pump_alerts_desk

    rows = subnets
    if rows is None:
        from internal.subnets.feed import load_subnets_for_display

        rows = load_subnets_for_display(timeout=subnet_timeout)
    return build_pump_alerts_desk(rows)


def load_pump_alerts_desk_payload(
    subnets: Optional[List[Dict[str, Any]]] = None,
    *,
    subnet_timeout: float = 4.0,
) -> Dict[str, Any]:
    """Desk JSON for SSR, /pump, and internal probes — matches GET /api/pump-alerts on worker."""
    try:
        from internal.data_volume import needs_worker_volume_proxy

        if needs_worker_volume_proxy():
            from internal.worker_proxy import fetch_worker_json_sync

            remote = fetch_worker_json_sync("/api/pump-alerts")
            if isinstance(remote, dict) and remote.get("error") != "worker_volume_proxy_failed":
                status = str(remote.get("status") or "").lower()
                if status not in ("error", "unavailable"):
                    return remote
    except Exception as exc:
        logger.warning("pump desk worker fetch failed, using local ladder: %s", exc)

    return _local_pump_alerts_desk(subnets, subnet_timeout=subnet_timeout)
