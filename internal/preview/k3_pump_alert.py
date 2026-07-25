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
            "exit_count": 0,
            "empty_message": (
                "No lead or confirmed motion right now. Early heat on today's pick stays on the "
                "dossier chip when flow warms."
            ),
            "error": None,
            "trust": {
                "ready": True,
                "headline_pct": 58,
                "headline_n": 14,
                "line": "",
            },
            "hero": {
                "netuid": 99,
                "name": "Apex",
                "phase": "ACCUMULATING",
                "timing": "lead",
                "score": 0.48,
                "trigger_score": 0.72,
                "distance": 0.24,
                "formation_pct": 62,
                "confirm_pct": 31,
                "subtitle": "Momentum breakout forming",
                "move": "BUILDING · Apex (SN99)",
                "thesis": "Flow and volume aligning ahead of price — 62% buys, vol 51%.",
                "trigger": "Best risk/reward band — chase only if you miss this window.",
                "badge": "BUILDING",
                "size_line": "50 τ ≈ 1.20% of float · healthy",
                "progress_series": [55, 58, 62, 67],
                "triad": {
                    "inflow_quiet_load": True,
                    "buy_pressure": True,
                    "price_coil": False,
                    "lit_count": 2,
                },
                "triad_labels": {
                    "inflow": "STRONG",
                    "pressure": "RISING",
                    "coil": "OPEN",
                },
            },
            "alerts": [
                {
                    "netuid": 99,
                    "name": "Apex",
                    "phase": "ACCUMULATING",
                    "timing": "lead",
                    "score": 0.48,
                    "trigger_score": 0.72,
                    "distance": 0.24,
                    "formation_pct": 62,
                    "confirm_pct": 31,
                    "move": "BUILDING · Apex (SN99)",
                    "thesis": "Flow and volume aligning ahead of price — 62% buys, vol 51%.",
                    "trigger": "Best risk/reward band — chase only if you miss this window.",
                    "badge": "BUILDING",
                    "buy_ratio": 0.62,
                    "volume_intensity": 0.51,
                    "size_line": "50 τ ≈ 1.20% of float · healthy",
                    "progress_series": [55, 58, 62, 67],
                    "triad": {
                        "inflow_quiet_load": True,
                        "buy_pressure": True,
                        "price_coil": False,
                        "lit_count": 2,
                    },
                    "triad_labels": {
                        "inflow": "STRONG",
                        "pressure": "RISING",
                        "coil": "OPEN",
                    },
                },
                {
                    "netuid": 42,
                    "name": "Subnet42",
                    "phase": "STIRRING",
                    "timing": "lead",
                    "score": 0.28,
                    "trigger_score": 0.72,
                    "distance": 0.44,
                    "formation_pct": 40,
                    "confirm_pct": 18,
                    "move": "WATCH · Subnet42 (SN42)",
                    "thesis": "Buy pressure building before price runs — 58% buy flow, volume still warming (24%).",
                    "trigger": "Entry window open — small size now or wait for BUILDING confirmation.",
                    "badge": "WARMING UP",
                    "buy_ratio": 0.58,
                    "volume_intensity": 0.24,
                    "triad": {
                        "inflow_quiet_load": True,
                        "buy_pressure": False,
                        "price_coil": False,
                        "lit_count": 1,
                    },
                    "triad_labels": {
                        "inflow": "WATCH",
                        "pressure": "FLAT",
                        "coil": "OPEN",
                    },
                },
                {
                    "netuid": 29,
                    "name": "Coldint",
                    "phase": "PUMPING",
                    "timing": "confirmed",
                    "score": 0.71,
                    "trigger_score": 0.72,
                    "distance": 0.01,
                    "formation_pct": 70,
                    "confirm_pct": 74,
                    "move": "CONFIRMED · Coldint (SN29)",
                    "thesis": "Move is live — you are not early. Use for exit sizing and rotation, not fresh entry.",
                    "trigger": "Do not chase; trim on EXIT WATCH or rotate to BUILDING names.",
                    "badge": "CHASE RISK",
                    "buy_ratio": 0.68,
                    "volume_intensity": 0.55,
                    "triad": {
                        "inflow_quiet_load": False,
                        "buy_pressure": True,
                        "price_coil": False,
                        "lit_count": 1,
                    },
                    "triad_labels": {
                        "inflow": "WATCH",
                        "pressure": "RISING",
                        "coil": "OPEN",
                    },
                },
            ],
        },
    }
