"""
Outcome Resolver — closes the prediction -> outcome leg of the loop.

For every pending prediction whose horizon has elapsed:
  1. Fetch the current price (reusing the taomarketcap price fetcher).
  2. Compute actual_pct = ((current - reference) / reference) * 100.
  3. Classify the outcome:
       - correct : direction matches AND magnitude within 50% of predicted
       - partial : direction matches BUT magnitude off by more than 50%
       - wrong   : direction is opposite to the prediction
       - expired : no price could be fetched after MAX_RETRIES attempts
  4. Persist the resolution via PredictionStore and return it for judging.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from data.prediction_store import PredictionStore

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
MAGNITUDE_TOLERANCE = 0.5  # within 50% of predicted magnitude => "correct"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class OutcomeResolver:
    """Resolves due predictions against live prices."""

    def __init__(
        self,
        store: Optional[PredictionStore] = None,
        price_provider=None,
        max_retries: int = MAX_RETRIES,
    ):
        self.store = store or PredictionStore()
        self.max_retries = max_retries
        # price_provider: callable(netuid) -> Optional[float]
        self.price_provider = price_provider or self._default_price_provider

    # ------------------------------------------------------------------
    # Price fetching
    # ------------------------------------------------------------------
    def _default_price_provider(self, netuid: Any) -> Optional[float]:
        """Fetch the current price for a netuid from the taomarketcap layer."""
        try:
            from fetchers.taomarketcap import get_subnet_data  # local import
            sn = get_subnet_data(int(netuid)) if netuid is not None else None
            if sn and sn.get("price"):
                return float(sn["price"])
        except Exception as exc:
            logger.debug("taomarketcap price fetch failed for %s: %s", netuid, exc)
        return None

    def _fetch_price(self, netuid: Any) -> Optional[float]:
        """Retry the price provider up to max_retries times."""
        for _ in range(self.max_retries):
            price = self.price_provider(netuid)
            if price and price > 0:
                return price
        return None

    # ------------------------------------------------------------------
    # Outcome classification
    # ------------------------------------------------------------------
    @staticmethod
    def classify(prediction: Dict[str, Any], current_price: float) -> Dict[str, Any]:
        """Compute actual_pct and the outcome label for a prediction."""
        ref = float(prediction.get("reference_price", 0) or 0)
        predicted_pct = float(prediction.get("predicted_pct", 0) or 0)
        if ref <= 0 or current_price <= 0:
            return {
                "actual_pct": None,
                "outcome": "expired",
                "current_price": current_price or None,
                "note": "Missing reference or current price.",
            }

        actual_pct = round((current_price - ref) / ref * 100, 2)
        predicted_dir = "up" if predicted_pct >= 0 else "down"
        actual_dir = "up" if actual_pct >= 0 else "down"

        if predicted_dir != actual_dir:
            outcome = "wrong"
            note = f"Direction mismatch: predicted {predicted_dir} {predicted_pct:+.2f}%, actual {actual_pct:+.2f}%."
        else:
            predicted_mag = abs(predicted_pct) or 1.0
            actual_mag = abs(actual_pct)
            # "within 50%" => actual magnitude is at least half of predicted.
            if actual_mag >= predicted_mag * (1 - MAGNITUDE_TOLERANCE):
                outcome = "correct"
                note = f"Direction & magnitude confirmed: {actual_pct:+.2f}% vs {predicted_pct:+.2f}% predicted."
            else:
                outcome = "partial"
                note = f"Direction right but magnitude short: {actual_pct:+.2f}% vs {predicted_pct:+.2f}% predicted."

        return {
            "actual_pct": actual_pct,
            "outcome": outcome,
            "current_price": current_price,
            "note": note,
        }

    # ------------------------------------------------------------------
    # Resolution loop
    # ------------------------------------------------------------------
    def resolve_due_predictions(self, now: Optional[datetime] = None) -> List[Dict[str, Any]]:
        """Resolve every due pending prediction. Returns the resolved entries."""
        now = now or datetime.now(timezone.utc)
        due = self.store.get_due(now)
        resolved: List[Dict[str, Any]] = []
        for pred in due:
            try:
                resolved_entry = self._resolve_one(pred)
                if resolved_entry:
                    resolved.append(resolved_entry)
            except Exception as exc:
                logger.warning("Failed to resolve prediction %s: %s", pred.get("id"), exc)
        return resolved

    def _resolve_one(self, prediction: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        pred_id = prediction.get("id")
        if not pred_id:
            return None

        netuid = prediction.get("netuid")
        current_price = self._fetch_price(netuid)
        classification = self.classify(prediction, current_price or 0)

        resolution = {
            **classification,
            "resolved_at": _now_iso(),
            "reference_price": float(prediction.get("reference_price", 0) or 0),
            "predicted_pct": float(prediction.get("predicted_pct", 0) or 0),
            "direction": prediction.get("direction"),
            "netuid": netuid,
            "subnet": prediction.get("subnet") or prediction.get("name"),
        }
        return self.store.resolve(pred_id, resolution)
