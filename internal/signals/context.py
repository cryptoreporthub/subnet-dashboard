"""Jinja context hooks for signals and alerts (Phase L)."""

from __future__ import annotations

import logging
from typing import Any, Dict

from internal.signals.alerts import AlertEngine
from internal.signals.pipeline import generate_live_signals
from internal.signals.store import SignalStore

logger = logging.getLogger(__name__)


def build_signals_context(refresh: bool = False) -> Dict[str, Any]:
    """Return ``signals``, ``alerts``, and ``signal_summary`` for GET /."""
    try:
        if refresh:
            result = generate_live_signals(persist=True)
            signals = result.get("signals") or []
        else:
            signals = SignalStore().latest_all()
            if not signals:
                result = generate_live_signals(persist=True)
                signals = result.get("signals") or []
        summary = SignalStore().summary().get("summary") or {}
        alerts_payload = AlertEngine().recent_alerts(limit=20, active_only=True)
        return {
            "signals": signals,
            "alerts": alerts_payload.get("alerts") or [],
            "signal_summary": summary,
        }
    except Exception as exc:
        logger.warning("Signals context unavailable: %s", exc)
        return {
            "signals": [],
            "alerts": [],
            "signal_summary": {
                "total_subnets": 0,
                "buy_count": 0,
                "sell_count": 0,
                "neutral_count": 0,
                "buy_sell_ratio": 0.0,
                "avg_confidence": 0.0,
            },
        }
