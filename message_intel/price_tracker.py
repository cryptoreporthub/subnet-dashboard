"""
Price Tracker — fetches TAO/USD price snapshots and outcome tracking.

Uses the CoinGecko public API to record price at message time and
check outcomes at +1h, +4h, +24h, +7d intervals.

Per-subnet alpha token price tracking is layered on top: each subnet's
alpha token price is fetched from the same taomarketcap data source the
dashboard already uses, so message outcomes are measured against the
specific subnet the message was about (not TAO/USD).
"""

import json
import logging
import os
import threading
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

COINGECKO_API = "https://api.coingecko.com/api/v3/simple/price?ids=bittensor&vs_currencies=usd"
_PRICE_CACHE: Dict[str, Any] = {}
_PRICE_CACHE_TTL = 60  # seconds

# Per-subnet alpha token price cache (keyed by netuid).
_SUBNET_PRICE_CACHE: Dict[int, Dict[str, Any]] = {}
_SUBNET_PRICE_CACHE_TTL = 60  # seconds
_ALL_SUBNET_PRICE_CACHE: Dict[str, Any] = {"data": None, "cached_at": 0}
# Intentionally short so the baseline tracker never serves data staler than
# the shared taomarketcap SQLite cache the rest of the app reads from.
_ALL_SUBNET_PRICE_CACHE_TTL = 15  # seconds

BASELINE_FILE = os.environ.get("PRICE_BASELINE_FILE", "data/price_baselines.json")
BASELINE_RETENTION_DAYS = 7
APP_BASE_URL = os.environ.get("APP_BASE_URL", "https://subnet-dashboard.fly.dev").rstrip("/")


def _fetch_all_subnets_from_taomarketcap() -> Optional[list]:
    """Fetch all subnets from the taomarketcap fetcher the app already uses."""
    try:
        from fetchers.taomarketcap import get_all_subnets
        subnets = get_all_subnets()
        if subnets:
            return subnets
    except Exception as e:
        logger.warning("taomarketcap fetch failed: %s", e)
    return None


def _fetch_all_subnets_from_app_api() -> Optional[list]:
    """Fallback: fetch subnets from the app's own /api/subnets endpoint."""
    try:
        url = f"{APP_BASE_URL}/api/subnets"
        req = urllib.request.Request(url, headers={"User-Agent": "SubnetDashboard/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
            subnets = data.get("subnets") if isinstance(data, dict) else None
            if subnets:
                return subnets
    except Exception as e:
        logger.warning("App /api/subnets fallback fetch failed: %s", e)
    return None


def _subnet_to_price_dict(sn: Dict[str, Any]) -> Dict[str, Any]:
    """Normalise a taomarketcap subnet row into a price-tracking dict."""
    return {
        "netuid": int(sn.get("netuid", 0) or 0),
        "name": sn.get("name") or f"SN{sn.get('netuid', 0)}",
        "price": float(sn.get("price", 0) or 0),
        "price_24h_change": float(sn.get("price_change_24h", 0) or 0),
        "price_7d_change": float(sn.get("price_change_7d", 0) or 0),
        "price_30d_change": float(sn.get("price_change_30d", 0) or 0),
        "market_cap": float(sn.get("market_cap", 0) or 0),
        "volume": float(sn.get("volume", 0) or 0),
    }


def fetch_all_subnet_prices() -> Dict[int, Dict[str, Any]]:
    """
    Fetch current alpha token prices for all subnets.

    Returns a dict keyed by netuid, each value containing at least
    ``price``, ``price_24h_change``, ``price_7d_change``, ``netuid`` and
    ``name``.

    This reads directly from the shared taomarketcap SQLite cache
    (``fetchers.taomarketcap.get_all_subnets``) that the dashboard's
    ``/api/subnets``, Undervalued Radar and SimiVision sections all use, so
    every endpoint derives 24h/7d change from the *same* snapshot. A very
    short in-process cache (15s) only guards against redundant SQLite reads
    within a single request batch; it is intentionally shorter than the
    shared cache TTL so it can never serve data staler than the shared cache.
    """
    cached = _ALL_SUBNET_PRICE_CACHE.get("data")
    cached_at = _ALL_SUBNET_PRICE_CACHE.get("cached_at", 0)
    if cached is not None and (time.time() - cached_at) < _ALL_SUBNET_PRICE_CACHE_TTL:
        return cached

    subnets = _fetch_all_subnets_from_taomarketcap()
    if not subnets:
        subnets = _fetch_all_subnets_from_app_api()

    result: Dict[int, Dict[str, Any]] = {}
    if subnets:
        for sn in subnets:
            try:
                price_data = _subnet_to_price_dict(sn)
            except (TypeError, ValueError):
                continue
            netuid = price_data["netuid"]
            if netuid:
                result[netuid] = price_data
                _SUBNET_PRICE_CACHE[netuid] = {
                    "data": price_data,
                    "cached_at": time.time(),
                }

    if result:
        _ALL_SUBNET_PRICE_CACHE["data"] = result
        _ALL_SUBNET_PRICE_CACHE["cached_at"] = time.time()
        logger.info("Fetched prices for %d subnets", len(result))
    return result


def fetch_subnet_price(netuid: int) -> Optional[Dict[str, Any]]:
    """
    Fetch the current alpha token price for a specific subnet.

    Uses the same taomarketcap data source the app already uses, with a
    60-second cache. Falls back to the app's own /api/subnets endpoint if
    the direct taomarketcap call fails.

    Returns a dict with at least: ``price``, ``price_24h_change``,
    ``price_7d_change``, ``netuid`` and ``name`` — or None on failure.
    """
    netuid = int(netuid)
    cached = _SUBNET_PRICE_CACHE.get(netuid)
    if cached and (time.time() - cached.get("cached_at", 0)) < _SUBNET_PRICE_CACHE_TTL:
        return cached.get("data")

    # Try the all-subnets cache / fetch first (single network round-trip).
    all_prices = fetch_all_subnet_prices()
    if netuid in all_prices:
        return all_prices[netuid]

    # Direct lookup against the taomarketcap fetcher.
    try:
        from fetchers.taomarketcap import get_subnet_data
        sn = get_subnet_data(netuid)
        if sn:
            price_data = _subnet_to_price_dict(sn)
            _SUBNET_PRICE_CACHE[netuid] = {"data": price_data, "cached_at": time.time()}
            return price_data
    except Exception as e:
        logger.warning("Direct subnet price fetch failed for netuid %d: %s", netuid, e)

    return None


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
        self._baseline_running = False
        self._baseline_thread: Optional[threading.Thread] = None

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

    def snapshot_subnet(self, message_id: int, netuid: int) -> Optional[float]:
        """
        Record an alpha-token price snapshot for a specific subnet message.

        Args:
            message_id: Database ID of the message.
            netuid: Subnet netuid whose alpha token price to record.

        Returns:
            The price recorded, or None if fetch failed.
        """
        price_data = fetch_subnet_price(netuid)
        if price_data is None:
            logger.warning(
                "No subnet price for netuid %s (message %d); skipping snapshot",
                netuid, message_id,
            )
            return None
        price = price_data.get("price")
        if price is None:
            return None
        if self.db is not None:
            self.db.save_price_snapshot(message_id, price, netuid=netuid)
            logger.info(
                "Subnet %s (%s) price snapshot for message %d: $%.8f",
                netuid, price_data.get("name"), message_id, price,
            )
        return price

    def check_outcomes(self) -> None:
        """
        Background task: check outcomes for unresolved messages.

        For messages with a recorded ``netuid``, the outcome is measured
        against that subnet's alpha token price (batch-fetched once per
        run). Messages without a netuid fall back to the legacy TAO/USD
        price path for backwards compatibility.
        """
        if self.db is None:
            return

        unresolved = self.db.get_unresolved_outcomes()
        if not unresolved:
            return

        # Group by netuid so we can batch-fetch each subnet's price once.
        # netuid=None (legacy snapshots) are handled via the TAO/USD path.
        netuids = {msg.get("netuid") for msg in unresolved if msg.get("netuid") is not None}
        subnet_prices: Dict[int, Optional[float]] = {}
        if netuids:
            all_prices = fetch_all_subnet_prices()
            for netuid in netuids:
                price_data = all_prices.get(netuid) or fetch_subnet_price(netuid)
                subnet_prices[netuid] = price_data.get("price") if price_data else None

        tao_price: Optional[float] = None

        for msg in unresolved:
            message_id = msg["id"]
            snapshot_price = msg.get("tao_usd_price")
            snapshot_ts = msg.get("snapshot_timestamp")
            netuid = msg.get("netuid")
            if snapshot_price is None or snapshot_ts is None:
                continue

            try:
                snapshot_dt = datetime.fromisoformat(snapshot_ts)
            except (ValueError, TypeError):
                continue

            hours_elapsed = (
                datetime.now(timezone.utc) - snapshot_dt.replace(tzinfo=timezone.utc)
            ).total_seconds() / 3600.0

            # Resolve the current price for this message's subnet.
            if netuid is not None:
                current_price = subnet_prices.get(netuid)
            else:
                # Legacy path: TAO/USD.
                if tao_price is None:
                    tao_price = fetch_tao_usd()
                current_price = tao_price

            if current_price is None:
                continue

            if snapshot_price == 0:
                continue

            # Compute price change (subnet alpha token price, not TAO/USD).
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
                    "Outcome for message %d (netuid=%s): %s (%.2f%%)",
                    message_id,
                    netuid,
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

    # ── Baseline price recording ─────────────────────────────────────

    def record_baseline_prices(self) -> None:
        """
        Record a baseline price snapshot for every tracked subnet.

        Writes to ``data/price_baselines.json`` so the learning loop has
        price history from day one, even before messages start flowing.
        Keeps only the last 7 days of entries.
        """
        all_prices = fetch_all_subnet_prices()
        if not all_prices:
            logger.warning("No subnet prices available for baseline recording")
            return

        now_iso = datetime.now(timezone.utc).isoformat()
        new_entries = [
            {
                "netuid": data["netuid"],
                "name": data.get("name"),
                "price": data.get("price"),
                "price_24h_change": data.get("price_24h_change"),
                "price_7d_change": data.get("price_7d_change"),
                "timestamp": now_iso,
            }
            for data in all_prices.values()
        ]

        existing: list = []
        try:
            os.makedirs(os.path.dirname(BASELINE_FILE) or ".", exist_ok=True)
            if os.path.exists(BASELINE_FILE):
                with open(BASELINE_FILE, "r", encoding="utf-8") as fh:
                    loaded = json.load(fh)
                    if isinstance(loaded, list):
                        existing = loaded
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Could not read baseline file (%s): %s", BASELINE_FILE, e)
            existing = []

        existing.extend(new_entries)

        # Trim to the retention window.
        cutoff = datetime.now(timezone.utc) - timedelta(days=BASELINE_RETENTION_DAYS)
        trimmed: list = []
        for entry in existing:
            ts = entry.get("timestamp")
            if not ts:
                trimmed.append(entry)
                continue
            try:
                entry_dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                if entry_dt.tzinfo is None:
                    entry_dt = entry_dt.replace(tzinfo=timezone.utc)
                if entry_dt >= cutoff:
                    trimmed.append(entry)
            except (ValueError, TypeError):
                trimmed.append(entry)

        try:
            with open(BASELINE_FILE, "w", encoding="utf-8") as fh:
                json.dump(trimmed, fh, indent=2)
            logger.info(
                "Recorded baseline prices for %d subnets (total entries: %d)",
                len(new_entries), len(trimmed),
            )
        except OSError as e:
            logger.error("Failed to write baseline file: %s", e)

    def start_baseline_recording(self, interval: int = 300) -> None:
        """
        Start a background thread that records baseline prices periodically.

        Args:
            interval: Seconds between recordings (default 300 = 5 min).
        """
        if self._baseline_running:
            return
        self._baseline_running = True

        def _loop():
            while self._baseline_running:
                try:
                    self.record_baseline_prices()
                except Exception as e:
                    logger.error("Baseline recording error: %s", e)
                time.sleep(interval)

        self._baseline_thread = threading.Thread(target=_loop, daemon=True)
        self._baseline_thread.start()
        logger.info(
            "Baseline price recorder started (interval=%ds)", interval
        )

    def stop(self) -> None:
        self._running = False
        self._baseline_running = False