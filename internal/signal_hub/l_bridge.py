"""Publish hub anomalies to Phase L store + alerts (decoupled bridge)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


def _utcnow_z() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def hub_signals_to_store_rows(anomalies: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Map hub anomalies to Phase L SignalStore rows."""
    rows: List[Dict[str, Any]] = []
    for hit in anomalies:
        sid = hit.get("subnet_id")
        if sid is None:
            continue
        direction = str(hit.get("direction") or "neutral")
        signal_type = "buy" if direction == "bullish" else "sell" if direction == "bearish" else "neutral"
        parts = [str(hit.get("type"))]
        if hit.get("z_score") is not None:
            parts.append(f"z={hit['z_score']}")
        if hit.get("roc_pct") is not None:
            parts.append(f"roc={hit['roc_pct']:+.1f}%")
        if hit.get("volume_ratio") is not None:
            parts.append(f"vol={hit['volume_ratio']:.1f}x")
        rows.append(
            {
                "subnet_id": sid,
                "name": hit.get("name"),
                "signal_type": signal_type,
                "confidence": 0.7 if hit.get("severity") == "warning" else 0.85,
                "source_expert": "hub",
                "timestamp": _utcnow_z(),
                "evidence": " · ".join(parts),
                "hub": dict(hit),
            }
        )
    return rows


def publish_to_phase_l(
    anomalies: List[Dict[str, Any]],
    *,
    persist_signals: bool = True,
) -> Dict[str, Any]:
    """Write signals.json + alerts.json via public L APIs."""
    signals = hub_signals_to_store_rows(anomalies)
    changed: List[Dict[str, Any]] = []
    alerts_created: List[Dict[str, Any]] = []

    if persist_signals and signals:
        try:
            from internal.signals.store import SignalStore

            changed = SignalStore().append_many(signals)
        except Exception as exc:
            logger.warning("Hub signal persist failed: %s", exc)

    try:
        from internal.signals.alerts import AlertEngine

        engine = AlertEngine()
        for hit in anomalies:
            sid = hit.get("subnet_id")
            atype = str(hit.get("type") or "hub_anomaly")
            dedupe = f"hub_{atype}_{sid}" if sid is not None else f"hub_{atype}"
            msg_parts = [atype.replace("_", " ")]
            if sid is not None:
                msg_parts.insert(0, f"SN{sid}")
            if hit.get("name"):
                msg_parts.append(str(hit["name"]))
            result = engine.create_alert(
                {
                    "alert_type": "hub_anomaly",
                    "message": " ".join(msg_parts),
                    "severity": str(hit.get("severity") or "info"),
                    "subnet_id": sid,
                    "dedupe_key": dedupe,
                    "details": dict(hit),
                }
            )
            if result.get("alert") and not result.get("deduped"):
                alerts_created.append(result["alert"])
    except Exception as exc:
        logger.warning("Hub alert publish failed: %s", exc)

    return {
        "signals_written": len(changed),
        "alerts_created": len(alerts_created),
        "signals": signals,
    }
