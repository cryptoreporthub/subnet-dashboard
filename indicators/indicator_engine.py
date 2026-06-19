"""
Indicator engine: fetches price data, computes technical signals, records them,
and exposes summary / per-pair / signal state.
"""

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from data.price_fetcher import PriceFetcher
from indicators.crossover_detector import detect_all_crossovers
from indicators.learning import load_thresholds
from indicators.macd import compute_macd
from indicators.momentum import compute_momentum
from indicators.rsi import compute_rsi
from internal.signals.signal_tracker import SignalTracker

PRICE_PAIRS_PATH = os.environ.get("PRICE_PAIRS_PATH", "config/price_pairs.json")
SIGNAL_TYPES_PATH = os.environ.get("SIGNAL_TYPES_PATH", "config/signal_types.json")
INDICATOR_STATE_PATH = os.environ.get("INDICATOR_STATE_PATH", "data/indicator_state.json")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_json(path: str) -> Dict[str, Any]:
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def _save_json(path: str, data: Dict[str, Any]) -> None:
    dir_name = os.path.dirname(path)
    if dir_name and not os.path.exists(dir_name):
        os.makedirs(dir_name, exist_ok=True)
    temp_path = path + ".tmp"
    with open(temp_path, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(temp_path, path)


def _load_price_pairs(path: str = PRICE_PAIRS_PATH) -> List[Dict[str, Any]]:
    data = _load_json(path)
    if isinstance(data, list):
        return data
    return data.get("pairs", [])


def _load_signal_types(path: str = SIGNAL_TYPES_PATH) -> Dict[str, Any]:
    data = _load_json(path)
    return data.get("signal_types", {})


def _classify_signal(
    rsi: Optional[float],
    macd: Optional[Dict[str, Any]],
    momentum: Optional[float],
    thresholds: Dict[str, float],
    crosses: List[Dict],
) -> Dict[str, Any]:
    """Classify the dominant signal type, action, and conviction."""
    rsi_oversold = thresholds.get("rsi_oversold", 30.0)
    rsi_overbought = thresholds.get("rsi_overbought", 70.0)
    momentum_threshold = thresholds.get("momentum_threshold", 3.0)

    cross_types = {c.get("type") for c in crosses}
    macd_bullish = macd is not None and macd.get("trend") == "bullish"
    macd_bearish = macd is not None and macd.get("trend") == "bearish"

    # 1. Breakout / mean-reversion from crossovers.
    if "golden_cross" in cross_types or "macd_bullish_cross" in cross_types:
        return {"signal_type": "breakout", "action": "accumulate", "priority": 100}
    if "death_cross" in cross_types or "macd_bearish_cross" in cross_types:
        return {"signal_type": "breakout", "action": "reduce", "priority": 100}

    # 2. Mean-reversion via RSI extremes.
    if rsi is not None and rsi < rsi_oversold and macd_bullish:
        return {"signal_type": "mean_reversion", "action": "accumulate", "priority": 90}
    if rsi is not None and rsi > rsi_overbought and macd_bearish:
        return {"signal_type": "mean_reversion", "action": "reduce", "priority": 90}

    # 3. Momentum continuation.
    if momentum is not None:
        if momentum > momentum_threshold and macd_bullish:
            return {"signal_type": "momentum", "action": "accumulate", "priority": 80}
        if momentum < -momentum_threshold and macd_bearish:
            return {"signal_type": "momentum", "action": "reduce", "priority": 80}

    # 4. Trend regime.
    if macd_bullish:
        return {"signal_type": "trend", "action": "accumulate", "priority": 60}
    if macd_bearish:
        return {"signal_type": "trend", "action": "reduce", "priority": 60}

    return {"signal_type": "neutral", "action": "hold", "priority": 50}


def _compute_conviction(
    classification: Dict[str, Any],
    rsi: Optional[float],
    macd: Optional[Dict[str, Any]],
    momentum: Optional[float],
    thresholds: Dict[str, float],
) -> float:
    """Compute a 0-100 conviction score for the dominant signal."""
    base = float(classification.get("priority", 50))
    conviction = base

    if rsi is not None:
        rsi_distance = abs(rsi - 50)
        conviction += rsi_distance / 50 * 15  # max 15 point tailwind

    if macd is not None:
        hist = abs(macd.get("histogram", 0.0) or 0.0)
        conviction += min(10.0, hist * 10)

    if momentum is not None:
        conviction += min(10.0, abs(momentum) / 2.0)

    floor = thresholds.get("conviction_floor", 30.0)
    return round(min(100.0, max(floor, conviction)), 2)


class IndicatorEngine:
    """Fetch prices, compute indicators, emit signals, and persist state."""

    def __init__(
        self,
        fetcher: Optional[PriceFetcher] = None,
        tracker: Optional[SignalTracker] = None,
        state_path: str = INDICATOR_STATE_PATH,
    ):
        self.fetcher = fetcher or PriceFetcher()
        self.tracker = tracker or SignalTracker()
        self.state_path = state_path
        self.price_pairs = _load_price_pairs()
        self.signal_types = _load_signal_types()

    def _record_indicator_signal(self, pair: str, classification: Dict[str, Any], conviction: float) -> None:
        """Push the indicator signal into the shared SignalTracker."""
        try:
            self.tracker.record_signal(
                asset=pair.split("-")[0],
                source="indicators",
                timestamp=_now_iso(),
                metadata={
                    "pair": pair,
                    "signal_type": classification.get("signal_type"),
                    "action": classification.get("action"),
                    "conviction": conviction,
                },
            )
        except Exception:
            # Non-blocking: indicator state remains useful even if signal tracker fails.
            pass

    def analyze_pair(self, pair_cfg: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze a single price pair and return a full signal record."""
        pair = pair_cfg.get("pair", "")
        symbol = pair_cfg.get("symbol", pair.split("-")[0])
        cg_id = pair_cfg.get("cg_id")
        vs_currency = pair_cfg.get("vs_currency", "usd")
        days = pair_cfg.get("days", 30)

        record: Dict[str, Any] = {
            "pair": pair,
            "symbol": symbol,
            "timestamp": _now_iso(),
            "error": None,
        }

        try:
            df = self.fetcher.fetch_market_chart(cg_id, days=days, vs_currency=vs_currency)
            prices = df["price"].tolist()

            rsi = compute_rsi(prices)
            macd = compute_macd(prices)
            momentum = compute_momentum(prices, period=10)

            macd_series = None
            signal_series = None
            if macd is not None:
                # Recompute full MACD line and signal line for crossover detection.
                import pandas as pd
                series = pd.Series(prices)
                line = series.ewm(span=12, adjust=False).mean() - series.ewm(span=26, adjust=False).mean()
                sig = line.ewm(span=9, adjust=False).mean()
                macd_series = line.tolist()
                signal_series = sig.tolist()

            thresholds = load_thresholds()
            crosses = detect_all_crossovers(prices, macd_series, signal_series)
            classification = _classify_signal(rsi, macd, momentum, thresholds, crosses)
            conviction = _compute_conviction(classification, rsi, macd, momentum, thresholds)

            record["indicators"] = {
                "rsi": rsi,
                "macd": macd,
                "momentum": momentum,
            }
            record["crossovers"] = crosses
            record["signal_type"] = classification["signal_type"]
            record["action"] = classification["action"]
            record["conviction"] = conviction
            record["prices_sampled"] = len(prices)
            record["latest_price"] = round(float(prices[-1]), 6) if prices else None

            self._record_indicator_signal(pair, classification, conviction)
        except Exception as exc:
            record["error"] = str(exc)
            record["signal_type"] = "neutral"
            record["action"] = "hold"
            record["conviction"] = thresholds.get("conviction_floor", 30.0) if "thresholds" in dir() else 30.0

        return record

    def run(self) -> Dict[str, Any]:
        """Run indicator analysis for every configured pair."""
        results = [self.analyze_pair(p) for p in self.price_pairs]
        state = {
            "updated_at": _now_iso(),
            "pairs": {r["pair"]: r for r in results},
            "signals": results,
        }
        _save_json(self.state_path, state)
        return state

    def get_state(self) -> Dict[str, Any]:
        """Return the persisted indicator state (or run once if missing)."""
        state = _load_json(self.state_path)
        if not state:
            return self.run()
        return state

    def get_pair(self, pair: str) -> Optional[Dict[str, Any]]:
        """Return a single pair's indicator record."""
        return self.get_state().get("pairs", {}).get(pair)

    def backtest_data(self, pair: str) -> Dict[str, Any]:
        """Return raw price + indicator history for the pair."""
        for p in self.price_pairs:
            if p.get("pair") == pair:
                df = self.fetcher.fetch_market_chart(
                    p.get("cg_id"), days=p.get("days", 30), vs_currency=p.get("vs_currency", "usd")
                )
                prices = df["price"].tolist()
                return {
                    "pair": pair,
                    "prices": prices,
                    "timestamps": [int(t) for t in df["timestamp"].tolist()],
                    "rsi": compute_rsi(prices),
                    "macd": compute_macd(prices),
                    "momentum": compute_momentum(prices, period=10),
                }
        return {"error": "pair not configured"}
