"""
Ruggers Watchlist — backward-compatible facade over Whale Intelligence.

The ruggers dimension is one of six tracked by the full Whale Intelligence
service. These endpoints remain for existing integrations.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import os

from internal.whales.service import WhaleIntelligenceService

DEFAULT_CONFIG_PATH = os.environ.get("WHALES_CONFIG_PATH", "config/whales.json")
DEFAULT_DATA_PATH = os.environ.get("WHALES_DATA_PATH", "data/whale_intelligence.json")


class RuggerWatchlist:
    """Thin wrapper: ruggers are tracked inside WhaleIntelligenceService."""

    def __init__(
        self,
        config_path: Optional[str] = None,
        data_path: Optional[str] = None,
        service: Optional[WhaleIntelligenceService] = None,
    ):
        if service is not None:
            self._service = service
        else:
            cfg = config_path or os.environ.get("WHALES_CONFIG_PATH", "config/whales.json")
            path = data_path or os.environ.get("WHALES_DATA_PATH", "data/whale_intelligence.json")
            if not os.path.exists(cfg):
                cfg = "config/whales.json"
            self._service = WhaleIntelligenceService(
                config_path=cfg,
                data_path=path,
            )

    def record_event(
        self,
        wallet: str,
        netuid: int,
        side: str,
        amount_tao: float,
        timestamp=None,
        **kwargs,
    ) -> Dict[str, Any]:
        return self._service.record_event(
            wallet=wallet,
            netuid=netuid,
            side=side,
            amount_tao=amount_tao,
            timestamp=timestamp,
            **kwargs,
        )

    def get_watchlist(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        return self._service.get_rugger_watchlist(limit)

    def get_profile(self, wallet: str) -> Optional[Dict[str, Any]]:
        return self._service.get_profile(wallet)

    def get_active_alerts(self) -> List[Dict[str, Any]]:
        return self._service.get_active_alerts().get("rugger_alerts", [])

    def get_subnet_risk(self, netuid: int) -> Dict[str, Any]:
        flow = self._service.get_subnet_flow(netuid)
        ruggers = flow.get("by_classification", {}).get("ruggers", [])
        risk: Dict[str, Any] = {
            "netuid": int(netuid),
            "rugger_count": len(ruggers),
            "ruggers": ruggers,
            "data_available": flow.get("data_available", False),
            "source": flow.get("source", "ledger"),
            "reason": flow.get("reason"),
        }
        if flow.get("data_available"):
            risk["avoid_follow"] = flow.get("avoid_follow", False)
        return risk

    def discount_score(self, netuid: int, base_score: float) -> Tuple[float, Dict[str, Any]]:
        return self._service.discount_score(netuid, base_score)

    def summary(self) -> Dict[str, Any]:
        s = self._service.summary()
        return {
            "status": "success",
            "updated_at": s.get("updated_at"),
            "config": s.get("config"),
            "data_available": s.get("data_available", False),
            "source": s.get("source", "ledger"),
            "reason": s.get("reason"),
            "stats": {
                "total_wallets_tracked": s["stats"]["total_wallets_tracked"],
                "rugger_count": s["stats"]["by_classification"].get("ruggers", 0),
                "open_positions": s["stats"]["open_positions"],
                "total_flips": s["stats"]["closed_trades"],
                "total_events": s["stats"]["total_events"],
            },
            "thresholds_hours": s.get("config", {}).get("flip_thresholds_hours"),
            "note": "Ruggers are one dimension of /api/whales — see /api/whales/dimensions",
        }
