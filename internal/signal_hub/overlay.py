"""Council overlay — bounded expert enrichment from hub anomalies."""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

from internal.signal_hub.state import load_hub_state

OVERLAY_MAX_BOOST = float(os.environ.get("HUB_OVERLAY_MAX_BOOST", "0.05"))
CORE_EXPERTS = ("quant", "hype", "dark_horse", "technical")


def build_hub_overlay(anomalies: list[Dict[str, Any]]) -> Dict[int, Dict[str, Any]]:
    """Map netuid → overlay payload for market_context."""
    overlay: Dict[int, Dict[str, Any]] = {}
    for row in anomalies:
        sid = row.get("subnet_id")
        if sid is None:
            continue
        key = int(sid)
        direction = str(row.get("direction") or "neutral")
        sign = 1.0 if direction == "bullish" else -1.0 if direction == "bearish" else 0.0
        severity = str(row.get("severity") or "info")
        weight = {"info": 0.4, "warning": 0.7, "critical": 1.0}.get(severity, 0.5)
        score = sign * weight
        existing = overlay.get(key)
        if existing:
            existing["anomaly_score"] = round(
                max(-1.0, min(1.0, float(existing["anomaly_score"]) + score * 0.5)),
                4,
            )
            types = list(existing.get("types") or [])
            types.append(row.get("type"))
            existing["types"] = types
        else:
            overlay[key] = {
                "anomaly_score": round(max(-1.0, min(1.0, score)), 4),
                "direction": direction,
                "types": [row.get("type")],
                "confidence": round(min(1.0, abs(score)), 4),
            }
    return overlay


def get_cached_hub_overlay() -> Dict[int, Dict[str, Any]]:
    state = load_hub_state()
    raw = state.get("overlay") or {}
    out: Dict[int, Dict[str, Any]] = {}
    for k, v in raw.items():
        try:
            out[int(k)] = dict(v) if isinstance(v, dict) else {}
        except (TypeError, ValueError):
            continue
    return out


def apply_hub_overlay(
    experts: Dict[str, float],
    overlay: Optional[Dict[str, Any]],
) -> Dict[str, float]:
    """Bounded nudge to expert contributions; no-op when overlay missing."""
    if not overlay:
        return experts
    try:
        score = float(overlay.get("anomaly_score", 0) or 0)
    except (TypeError, ValueError):
        return experts
    if score == 0:
        return experts
    boost = max(-OVERLAY_MAX_BOOST, min(OVERLAY_MAX_BOOST, score * OVERLAY_MAX_BOOST))
    direction = str(overlay.get("direction") or "neutral")
    adjusted = dict(experts)
    if direction == "bullish":
        for name in ("hype", "technical"):
            if name in adjusted:
                adjusted[name] = round(min(1.0, max(0.0, adjusted[name] + boost)), 4)
        if "quant" in adjusted:
            adjusted["quant"] = round(min(1.0, max(0.0, adjusted["quant"] + boost * 0.5)), 4)
    elif direction == "bearish":
        for name in ("technical", "dark_horse"):
            if name in adjusted:
                adjusted[name] = round(min(1.0, max(0.0, adjusted[name] - boost)), 4)
    return adjusted
