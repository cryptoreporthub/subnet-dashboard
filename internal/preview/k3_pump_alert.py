"""Static K3-8 Pump Alert preview context."""

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
            "count": 2,
            "empty_message": (
                "No names in PUMPING right now. Early heat stays on the dossier chip when the lead is warming."
            ),
            "error": None,
            "alerts": [
                {
                    "netuid": 29,
                    "name": "Coldint",
                    "phase": "PUMPING",
                    "score": 0.71,
                    "move": "IN PLAY · Coldint (SN29)",
                    "thesis": (
                        "Ladder says PUMPING — buy flow and volume already aligned. "
                        "This is motion, not the early heat chip. Flow 68% buy · vol 55%."
                    ),
                    "trigger": "Late if you chase; watch for COOLING before adding.",
                    "badge": "PUMPING",
                    "buy_ratio": 0.68,
                    "volume_intensity": 0.55,
                    "updated_at": "2026-07-19T08:00:00Z",
                },
                {
                    "netuid": 14,
                    "name": "TaoHash",
                    "phase": "PUMPING",
                    "score": 0.64,
                    "move": "IN PLAY · TaoHash (SN14)",
                    "thesis": (
                        "Ladder says PUMPING — buy flow and volume already aligned. "
                        "This is motion, not the early heat chip. Flow 61% buy · vol 48%."
                    ),
                    "trigger": "Late if you chase; watch for COOLING before adding.",
                    "badge": "PUMPING",
                    "buy_ratio": 0.61,
                    "volume_intensity": 0.48,
                    "updated_at": "2026-07-19T07:45:00Z",
                },
            ],
        },
    }
