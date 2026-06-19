"""
Technical Expert — brings indicator-layer signals into the Selector council.

Registers as the fourth expert alongside Quant, Hype, and Contrarian.
"""

import json
import os
from typing import Any, Dict, Optional

INDICATOR_STATE_PATH = os.environ.get("INDICATOR_STATE_PATH", "data/indicator_state.json")
PRICE_PAIRS_PATH = os.environ.get("PRICE_PAIRS_PATH", "config/price_pairs.json")


class TechnicalExpert:
    """Score subnets using technical indicator signals when a tracked pair matches."""

    def __init__(self, state_path: str = INDICATOR_STATE_PATH):
        self.state_path = state_path
        self._pair_map = self._build_pair_map()

    def _load_json(self, path: str) -> Any:
        if os.path.exists(path):
            try:
                with open(path, "r") as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    def _build_pair_map(self) -> Dict[str, str]:
        data = self._load_json(PRICE_PAIRS_PATH)
        pairs = data if isinstance(data, list) else data.get("pairs", [])
        mapping = {}
        for item in pairs:
            symbol = item.get("symbol", "").upper()
            if symbol:
                mapping[symbol] = item.get("pair", "")
        return mapping

    def _latest_indicator(self, pair: str) -> Optional[Dict[str, Any]]:
        state = self._load_json(self.state_path)
        return state.get("pairs", {}).get(pair)

    def analyze(self, subnet_id: int, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Return a technical opinion for the subnet.

        If the subnet name/symbol maps to a tracked indicator pair, the latest
        signal drives the score. Otherwise returns a neutral hold signal.
        """
        context = context or {}
        name = context.get("name", "").upper()
        symbol = context.get("symbol", "").upper()

        pair = self._pair_map.get(symbol) or self._pair_map.get(name)
        if pair:
            indicator = self._latest_indicator(pair)
            if indicator:
                action = indicator.get("action", "hold")
                conviction = indicator.get("conviction", 50.0)
                return {
                    "score": round(conviction / 100.0, 4),
                    "signal": action,
                    "pair": pair,
                    "signal_type": indicator.get("signal_type", "neutral"),
                    "metrics": {
                        "rsi": indicator.get("indicators", {}).get("rsi"),
                        "macd": indicator.get("indicators", {}).get("macd"),
                        "momentum": indicator.get("indicators", {}).get("momentum"),
                        "conviction": conviction,
                    },
                }

        return {
            "score": 0.5,
            "signal": "hold",
            "pair": pair,
            "signal_type": "neutral",
            "metrics": {"note": "no tracked indicator pair for this subnet"},
        }
