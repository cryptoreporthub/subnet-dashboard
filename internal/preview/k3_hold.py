"""Static K3 HOLD+candidate preview context (no hydrate, no pick engine)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from fastapi import Request


def _utcnow_z() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def build_k3_hold_preview_context(request: Request) -> Dict[str, Any]:
    """Full SSR context for /preview/k3-hold — target K3 dossier + action brief."""
    from internal.learning.dpick_copy import attach_brief_to_daily_pick
    from internal.learning.dpick_pump import attach_pump_chip_to_daily_pick
    from internal.subnet_names import enrich_subnet_rows, refresh_daily_pick_names

    subnets: List[Dict[str, Any]] = enrich_subnet_rows(
        [
            {"netuid": 99, "name": "SN99", "emission": 0.95, "price_change_24h": -5.2, "price_change_7d": -44.2, "volume": 52000, "buy_volume_24h": 7800, "sell_volume_24h": 2200},
            {"netuid": 14, "name": "TaoHash", "emission": 2.1, "price_change_24h": 1.1},
            {"netuid": 40, "name": "Chunking", "emission": 1.8, "price_change_24h": 0.5},
            {"netuid": 82, "name": "MinoS", "emission": 1.2, "price_change_24h": 2.0},
            {"netuid": 118, "name": "Ditto", "emission": 0.8, "price_change_24h": -0.3},
        ]
    )
    resolve_at = (datetime.now(timezone.utc) + timedelta(hours=4, minutes=12)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )

    daily = refresh_daily_pick_names(
        {
            "status": "ok",
            "date": datetime.now(timezone.utc).date().isoformat(),
            "action": "HOLD",
            "reason": "Conviction 23% — below the 45% bar for a sized 24h long",
            "pick": None,
            "candidate": {
                "subnet": {"netuid": 99, "name": "SN99", "symbol": "T99"},
                "final_confidence": 0.233,
                "action": "LONG",
                "reasons": ["Stochastic %K 98.1 (overbought)"],
                "audit": {
                    "concerns": [
                        "Subnet flagged as overvalued",
                        "Thin volume: $1,200 < $5k",
                    ]
                },
            },
            "horizon_views": {
                "default": "24h",
                "anchor": "24h",
                "chips": ["now", "24h", "7d"],
                "views": {
                    "now": {
                        "id": "now",
                        "label": "Now",
                        "lens": "council_hour",
                        "subnet": {"netuid": 14, "name": "TaoHash", "symbol": "TH"},
                        "conviction": 41,
                        "action": "LONG",
                    },
                    "24h": {
                        "id": "24h",
                        "label": "24h",
                        "lens": "council_day",
                        "subnet": {"netuid": 99, "name": "SN99", "symbol": "T99"},
                        "conviction": 23,
                        "action": "LONG",
                    },
                    "7d": {
                        "id": "7d",
                        "label": "7d",
                        "lens": "trend",
                        "subnet": {"netuid": 99, "name": "SN99", "symbol": "T99"},
                        "conviction": 19,
                        "action": "LONG",
                        "pct_7d": -44.2,
                        "note": "Trend lens — not graded",
                    },
                },
            },
            "temporal_badge": "LIVE · 4h 12m remaining",
            "ring_state": "fresh",
            "resolve_at": resolve_at,
            "grade_on_resolve": True,
            "time_horizon": "24h",
            "shortlist": [
                {
                    "netuid": 40,
                    "name": "Chunking",
                    "conviction": 31,
                    "role": "Higher emission but thinner liquidity",
                    "stance": "LONG",
                },
                {"netuid": 82, "name": "MinoS", "conviction": 28, "role": "Thin volume", "stance": "LONG"},
                {"netuid": 118, "name": "Ditto", "conviction": 26, "role": "Social buzz", "stance": "LONG"},
            ],
            "signals": [
                {"name": "RSI", "value": "98.1 overbought"},
                {"name": "7d price", "value": "-44.2%"},
            ],
            "judges": [
                {"name": "Oracle", "weight": 0.4, "delta": 0.02},
                {"name": "Echo", "weight": 0.25, "delta": -0.01},
                {"name": "Pulse", "weight": 0.35, "delta": 0.0},
            ],
        }
    )
    daily = attach_brief_to_daily_pick(daily)
    daily = attach_pump_chip_to_daily_pick(
        daily,
        subnets,
    )
    if not daily.get("pump_chip", {}).get("show"):
        from internal.learning.dpick_pump import build_pump_chip

        daily["pump_chip"] = build_pump_chip(
            99,
            next(s for s in subnets if s.get("netuid") == 99),
            ladder_entry={
                "phase": "STIRRING",
                "signal_snapshot": {"buy_ratio": 0.78, "volume_intensity": 0.42},
            },
        )

    return {
        "request": request,
        "public_base_url": str(request.base_url).rstrip("/"),
        "subnets": subnets,
        "data_source": "preview-mock",
        "daily_pick_stage": daily,
        "conviction_band": {"band": "low", "reason": "Below sized-long bar", "status": "ok"},
        "enrichment_badge": {"status": "pending", "label": "Whale flow"},
        "hybrid_trust": {"ready": True, "n": 443, "accuracy": 0.314},
        "trust_banner": {
            "ready": True,
            "graded": 443,
            "correct": 139,
            "wrong": 304,
            "accuracy": 0.314,
            "headline": "Last 443 graded: 31% directionally right",
            "note": "Accuracy is direction-only on graded token price outcomes — excludes expired/duplicate.",
        },
        "habit_watchlist": {"netuids": [], "count": 0},
        "habit_alerts": {"enabled": True, "delivery_mode": "off"},
        "story_path": {
            "data_available": True,
            "steps": [
                {"label": "1 · Signals", "title": "RSI crossover", "status": "done"},
                {"label": "2 · Council", "title": "Experts blend → Hype", "status": "done"},
                {"label": "3 · Pick", "title": "HOLD SN99 candidate", "status": "active"},
                {"label": "4 · Outcome", "title": "Pending resolve", "status": "pending"},
                {"label": "5 · Learn", "title": "Weight nudge", "status": "pending"},
            ],
        },
        "simivision": {"top": []},
        "signals": [],
        "alerts": [],
        "preview_mode": True,
    }
