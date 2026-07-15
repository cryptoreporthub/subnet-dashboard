"""§17.S3 — whale-flow enrichment badge (Nansen-style, honest-empty)."""

from __future__ import annotations

from typing import Any, Dict, Optional

from internal.whales.service import WhaleIntelligenceService

_BADGE_KIND = "whale_flow"
_DEFAULT_LABEL = "Smart money"


def empty_whale_flow_badge(reason: str = "no_pick") -> Dict[str, Any]:
    return {
        "kind": _BADGE_KIND,
        "label": _DEFAULT_LABEL,
        "status": "empty",
        "reason": reason,
    }


def whale_flow_badge_from_flow(flow: Dict[str, Any]) -> Dict[str, Any]:
    """Build badge from an existing ``get_subnet_flow`` payload."""
    netuid = flow.get("netuid")
    if not flow.get("data_available"):
        return {
            "kind": _BADGE_KIND,
            "label": _DEFAULT_LABEL,
            "status": "empty",
            "reason": flow.get("reason") or "no_events",
            "netuid": netuid,
        }

    open_pos = int(flow.get("open_positions") or 0)
    if flow.get("avoid_follow"):
        return {
            "kind": _BADGE_KIND,
            "label": "Rugger activity",
            "status": "live",
            "netuid": netuid,
            "open_positions": open_pos,
        }
    if flow.get("smart_money_present"):
        return {
            "kind": _BADGE_KIND,
            "label": "Smart money in",
            "status": "live",
            "netuid": netuid,
            "open_positions": open_pos,
        }
    if open_pos > 0:
        return {
            "kind": _BADGE_KIND,
            "label": "Whale positions",
            "status": "live",
            "netuid": netuid,
            "open_positions": open_pos,
        }
    return {
        "kind": _BADGE_KIND,
        "label": _DEFAULT_LABEL,
        "status": "empty",
        "reason": "no_positions",
        "netuid": netuid,
    }


def whale_flow_badge(
    netuid: int,
    *,
    flow: Optional[Dict[str, Any]] = None,
    service: Optional[WhaleIntelligenceService] = None,
) -> Dict[str, Any]:
    """Whale-flow badge for a subnet — live signal or explicit empty."""
    svc = service or WhaleIntelligenceService()
    payload = flow if flow is not None else svc.get_subnet_flow(int(netuid))
    if "netuid" not in payload:
        payload = {**payload, "netuid": int(netuid)}
    return whale_flow_badge_from_flow(payload)
