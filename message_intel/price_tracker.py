"""
Price Tracker — fetches TAO/USD price snapshots and outcome tracking.

Uses the CoinGecko public API to record price at message time and
check outcomes at +1h, +4h, +24h, +7d intervals.
"""

import json
import logging
import os
import threading
import time
import urllib.request
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

COINGECKO_API = "https://api.coingecko.com/api/v3/simple/price?ids=bittensor&vs_currencies=usd"
_PRICE_CACHE: Dict[str, Any] = {}
_PRICE_CACHE_TTL = 60  # seconds


def fetch_tao_usd() -> Optional[float]:
    """
    Fetch current TAO/USD price from CoinGecko.

    Returns:
        float price or None if fetch fails.
    """
    cached = _PRICE_CACHE.get("price")
    cached_at = _PRICE_CACHE.get("cached_at", 0)
    if cached is not None and (time.time() - cached_at) < _PRICE_CACHE_TTL:
        return cached

    try:
        req = urllib.request.Request(
            COINGECKO_API,
            headers={"User-Agent": "SubnetDashboard/1.0"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            price = data.get("bittensor", {}).get("usd")
            if price is not None:
                _PRICE_CACHE["price"] = price
                _PRICE_CACHE["cached_at"] = time.time()
                return float(price)
    except Exception as e:
        logger.warning("Failed to fetch TAO price: %s", e)

    # Fallback: try taostats
    try:
        req = urllib.request.Request(
            "https://api.taostats.io/api/v1/price/latest",
            headers={"User-Agent": "SubnetDashboard/1.0"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            price = data.get("data", {}).get("price")
            if price is not None:
                return float(price)
    except Exception as e:
        logger.warning("Failed to fetch TAO price from taostats: %s", e)

    return None


class PriceTracker:
    """
    Records price snapshots for high-conviction messages and
    checks outcomes at future intervals.
    """

    def __init__(self, db=None):
        self.db = db
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def set_db(self, db) -> None:
        """Set the database instance after initialization."""
        self.db = db

    def snapshot(self, message_id: int) -> Optional[float]:
        """
        Record a price snapshot for a message.

        Args:
            message_id: Database ID of the message.

        Returns:
            The price recorded, or None if fetch failed.
        """
        price = fetch_tao_usd()
        if price is not None and self.db is not None:
            self.db.save_price_snapshot(message_id, price)
            logger.info(
                "Price snapshot for message %d: $%.2f", message_id, price
            )
        return price

    def check_outcomes(self) -> None:
        """
        Background task: check outcomes for unresolved messages.

        Compares current price against the snapshot price and
        records pump metrics.
        """
        if self.db is None:
            return

        unresolved = self.db.get_unresolved_outcomes()
        if not unresolved:
            return

        current_price = fetch_tao_usd()
        if current_price is None:
            return

        for msg in unresolved:
            message_id = msg["id"]
            snapshot_price = msg.get("tao_usd_price")
            snapshot_ts = msg.get("snapshot_timestamp")
            if snapshot_price is None or snapshot_ts is None:
                continue

            try:
                snapshot_dt = datetime.fromisoformat(snapshot_ts)
            except (ValueError, TypeError):
                continue

            hours_elapsed = (
                datetime.now(timezone.utc) - snapshot_dt.replace(tzinfo=timezone.utc)
            ).total_seconds() / 3600.0

            # Compute price change
            pct_change = (
                (current_price - snapshot_price) / snapshot_price
            ) * 100.0

            outcome_data: Dict[str, Any] = {
                "price_1h": None,
                "price_4h": None,
                "price_24h": None,
                "price_7d": None,
                "pump_pct_max": None,
                "time_to_pump": None,
                "pump_duration": None,
                "resurgence": None,
                "outcome": None,
            }

            if hours_elapsed >= 1:
                outcome_data["price_1h"] = current_price
            if hours_elapsed >= 4:
                outcome_data["price_4h"] = current_price
            if hours_elapsed >= 24:
                outcome_data["price_24h"] = current_price
            if hours_elapsed >= 168:  # 7 days
                outcome_data["price_7d"] = current_price

            # Determine outcome
            if pct_change > 5.0:
                outcome_data["outcome"] = "pump"
                outcome_data["pump_pct_max"] = round(pct_change, 2)
                outcome_data["time_to_pump"] = round(hours_elapsed, 2)
            elif pct_change > 2.0:
                outcome_data["outcome"] = "mild_pump"
                outcome_data["pump_pct_max"] = round(pct_change, 2)
            elif pct_change < -5.0:
                outcome_data["outcome"] = "dump"
            elif pct_change < -2.0:
                outcome_data["outcome"] = "mild_dump"
            else:
                outcome_data["outcome"] = "stable"

            # Record the outcome if we have at least 1h data
            if outcome_data["price_1h"] is not None:
                self.db.save_price_outcome(message_id, outcome_data)
                logger.info(
                    "Outcome for message %d: %s (%.2f%%)",
                    message_id,
                    outcome_data["outcome"],
                    pct_change,
                )

    def start_background_checks(self, interval: int = 300) -> None:
        """
        Start a background thread that periodically checks outcomes.

        Args:
            interval: Seconds between checks (default 300 = 5 min).
        """
        if self._running:
            return
        self._running = True

        def _loop():
            while self._running:
                try:
                    self.check_outcomes()
                except Exception as e:
                    logger.error("Outcome check error: %s", e)
                time.sleep(interval)

        self._thread = threading.Thread(target=_loop, daemon=True)
        self._thread.start()
        logger.info(
            "Price outcome checker started (interval=%ds)", interval
        )

    def stop(self) -> None:
        self._running = False