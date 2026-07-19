"""Static K3-8b Lead scanner preview context."""

from __future__ import annotations

from typing import Any, Dict

from fastapi import Request


def build_k3_pump_alert_preview_context(request: Request) -> Dict[str, Any]:
    return {
        "request": request,
        "public_base_url": str(request.base_url).rstrip("/"),
        "preview_mode": True,
        "pump_alerts": {
            "status": "success",
            "count": 3,
            "early_count": 2,
            "confirmed_count": 1,
            "empty_message": (
                "No lead or confirmed motion right now. Early heat on today's pick stays on the "
                "dossier chip when flow warms."
            ),
            "error": None,
            "alerts": [
                {
                    "netuid": 99,
                    "name": "Apex",
                    "phase": "ACCUMULATING",
                    "timing": "lead",
                    "score": 0.48,
                    "move": "BUILDING · Apex (SN99)",
                    "thesis": "Flow and volume aligning ahead of price — 62% buys, vol 51%.",
                    "trigger": "Best risk/reward band — chase only if you miss this window.",
                    "badge": "BUILDING",
                    "buy_ratio": 0.62,
                    "volume_intensity": 0.51,
                },
                {
                    "netuid": 42,
                    "name": "Subnet42",
                    "phase": "STIRRING",
                    "timing": "lead",
                    "score": 0.28,
                    "move": "WATCH · Subnet42 (SN42)",
                    "thesis": "Buy pressure building before price runs — 58% buy flow, volume still warming (24%).",
                    "trigger": "Entry window open — small size now or wait for BUILDING confirmation.",
                    "badge": "EARLY",
                    "buy_ratio": 0.58,
                    "volume_intensity": 0.24,
                },
                {
                    "netuid": 29,
                    "name": "Coldint",
                    "phase": "PUMPING",
                    "timing": "confirmed",
                    "score": 0.71,
                    "move": "CONFIRMED · Coldint (SN29)",
                    "thesis": "Move is live — you are not early. Use for exit sizing and rotation, not fresh entry.",
                    "trigger": "Do not chase; trim on EXIT WATCH or rotate to BUILDING names.",
                    "badge": "CHASE RISK",
                    "buy_ratio": 0.68,
                    "volume_intensity": 0.55,
                },
            ],
        },
    }
