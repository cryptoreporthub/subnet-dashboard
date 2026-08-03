"""SSR preview for the tribunal hero — four states, hydrate off."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import Request

from internal.learning.dpick_tribunal import attach_tribunal_to_daily_pick


def _utcnow_z() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sealed_daily() -> Dict[str, Any]:
    resolve = (datetime.now(timezone.utc) + timedelta(minutes=56)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    return {
        "status": "ok",
        "date": datetime.now(timezone.utc).date().isoformat(),
        "action": "LONG",
        "reason": "",
        "generated_at": _utcnow_z(),
        "resolves_in": "56m",
        "temporal_badge": "Sealed · resolves in 56m",
        "time_horizon": "1h",
        "horizon": "1h",
        "pick": {
            "subnet": {
                "netuid": 64,
                "name": "Chutes",
                "symbol": "SN64",
                "description": "Compute",
            },
            "final_confidence": 0.72,
            "action": "LONG",
            "expert_contributions": {
                "quant": 0.82,
                "hype": 0.20,
                "dark_horse": 0.60,
                "technical": 0.77,
            },
            "prediction": {"resolve_at": resolve, "created_at": _utcnow_z(), "horizon_hours": 1},
        },
        "candidate": None,
    }


def _gated_daily() -> Dict[str, Any]:
    return {
        "status": "ok",
        "date": datetime.now(timezone.utc).date().isoformat(),
        "action": "HOLD",
        "reason": "Confidence 34% below 40% audit gate — no long call published",
        "generated_at": _utcnow_z(),
        "resolves_in": None,
        "temporal_badge": "Gate held",
        "time_horizon": "24h",
        "pick": None,
        "candidate": {
            "subnet": {
                "netuid": 99,
                "name": "Thirty Spokes",
                "symbol": "SN99",
                "description": "Inference",
            },
            "final_confidence": 0.34,
            "action": "LONG",
            "expert_contributions": {
                "quant": 0.51,
                "hype": 0.44,
                "dark_horse": 0.62,
                "technical": 0.48,
            },
        },
    }


def _forming_daily() -> Dict[str, Any]:
    return {
        "status": "pending",
        "date": datetime.now(timezone.utc).date().isoformat(),
        "action": "HOLD",
        "reason": "today's pick forming",
        "pick": None,
        "candidate": None,
    }


def _cold_daily() -> Dict[str, Any]:
    return {}


def _weighing_candidates() -> List[Dict[str, Any]]:
    """Proximity board mock — same shape as /api/simivision top rows (subset)."""
    return [
        {
            "netuid": 22,
            "name": "DeSearch",
            "proximity": 81,
            "conviction": 68,
            "deliberation_state": "NEAR-CALL",
            "expert_split": "Judge split · Quant leads",
            "leans": {"q": True, "h": False, "d": True, "t": True},
            "leans_label": "3 of 4 leaning buy",
        },
        {
            "netuid": 19,
            "name": "Blockmachine",
            "proximity": 63,
            "conviction": 55,
            "deliberation_state": "WEIGHING",
            "expert_split": "Judge split · Hype leads",
            "leans": {"q": True, "h": True, "d": False, "t": False},
            "leans_label": "split, quant + hype only",
        },
        {
            "netuid": 99,
            "name": "Thirty Spokes",
            "proximity": 47,
            "conviction": 41,
            "deliberation_state": "WEIGHING",
            "expert_split": "Judge split · Dark Horse leads",
            "leans": {"q": False, "h": False, "d": True, "t": False},
            "leans_label": "dark horse alone, early",
        },
        {
            "netuid": 118,
            "name": "Ditto",
            "proximity": 29,
            "conviction": 33,
            "deliberation_state": "FADING",
            "expert_split": "Judge split · Technical leads",
            "leans": {"q": False, "h": False, "d": False, "t": True},
            "leans_label": "technical only, watching",
        },
    ]


_FIXTURES = {
    "sealed": _sealed_daily,
    "gated": _gated_daily,
    "forming": _forming_daily,
    "cold": _cold_daily,
}


def build_tribunal_preview_context(
    request: Request,
    state: Optional[str] = None,
) -> Dict[str, Any]:
    key = (state or "sealed").strip().lower()
    if key not in _FIXTURES:
        key = "sealed"
    daily = attach_tribunal_to_daily_pick(_FIXTURES[key]())
    show_weighing = key in ("sealed", "gated")
    return {
        "request": request,
        "public_base_url": str(request.base_url).rstrip("/"),
        "preview_mode": True,
        "preview_state": key,
        "daily_pick_stage": daily,
        "tribunal": daily.get("tribunal") or {},
        "weighing_candidates": _weighing_candidates() if show_weighing else [],
        "data_source": "preview-mock",
    }
