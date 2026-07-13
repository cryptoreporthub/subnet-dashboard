"""Jinja context for signal hub (Phase O)."""

from __future__ import annotations

import logging
from typing import Any, Dict

from internal.signal_hub.tracker import hub_signals_list, hub_status

logger = logging.getLogger(__name__)


def build_signal_hub_context() -> Dict[str, Any]:
    try:
        status = hub_status(refresh=False)
        signals_payload = hub_signals_list()
        return {
            "signal_hub": {
                "status": status.get("hub") or {},
                "signals": signals_payload.get("signals") or [],
                "thresholds": status.get("thresholds") or {},
            }
        }
    except Exception as exc:
        logger.warning("Signal hub context unavailable: %s", exc)
        return {
            "signal_hub": {
                "status": {"active": False, "anomaly_count": 0, "signals_emitted": 0},
                "signals": [],
                "thresholds": {},
            }
        }
