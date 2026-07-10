"""Rotation-token watchlist prices (CoinGecko, cached). Ported from server_original."""

from __future__ import annotations

import json
import logging
import time
import urllib.request
from datetime import datetime, timezone
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

ROTATION_TOKENS = ["hyperliquid", "vvv", "near", "render", "fetch"]

COINGECKO_IDS = {
    "hyperliquid": "hyperliquid",
    "vvv": "venice-token",
    "near": "near",
    "render": "render-token",
    "fetch": "fetch-ai",
}

_PRICE_CACHE: Dict[str, Any] = {"data": None, "at": 0.0}
_CACHE_TTL = 60  # seconds


def fetch_rotation_token_prices() -> Dict[str, Dict[str, Any]]:
    """Fetch USD prices + 24h change; 60s cache with stale fallback."""
    now = time.time()
    cached = _PRICE_CACHE.get("data")
    if cached is not None and (now - _PRICE_CACHE.get("at", 0.0)) < _CACHE_TTL:
        return cached

    ids = ",".join(
        COINGECKO_IDS[sym] for sym in ROTATION_TOKENS if sym in COINGECKO_IDS
    )
    result: Dict[str, Dict[str, Any]] = {}
    if ids:
        try:
            url = (
                "https://api.coingecko.com/api/v3/simple/price"
                f"?ids={ids}&vs_currencies=usd&include_24hr_change=true"
            )
            req = urllib.request.Request(url, headers={"User-Agent": "SubnetDashboard/1.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                payload = json.loads(resp.read().decode())
        except Exception as exc:
            logger.warning("CoinGecko rotation-token price fetch failed: %s", exc)
            payload = None

        if isinstance(payload, dict):
            for sym in ROTATION_TOKENS:
                coin_id = COINGECKO_IDS.get(sym)
                entry = payload.get(coin_id) if coin_id else None
                if isinstance(entry, dict):
                    price = entry.get("usd")
                    change = entry.get("usd_24h_change")
                    result[sym] = {
                        "price": float(price) if price is not None else None,
                        "price_change_24h": round(float(change), 2)
                        if change is not None
                        else None,
                    }

    if result:
        _PRICE_CACHE["data"] = result
        _PRICE_CACHE["at"] = now
        return result
    return cached or {}


def _mirror_rotation_snapshot_to_soul_map(tokens: List[Dict[str, Any]]) -> bool:
    """Persist rotation-token snapshot into soul_map; return True if disposition changed."""
    try:
        from internal.council.weights import SOUL_MAP_PATH, _load_raw, _save_raw

        data = _load_raw(SOUL_MAP_PATH)
        sms = data.setdefault("soul_map_state", {})
        if not isinstance(sms, dict):
            sms = {}
            data["soul_map_state"] = sms

        prior = sms.get("rotation_tokens_snapshot") or {}
        prior_tokens = prior.get("tokens") if isinstance(prior, dict) else None
        changed = prior_tokens != tokens

        sms["rotation_tokens_snapshot"] = {
            "tokens": tokens,
            "updated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }
        _save_raw(data, SOUL_MAP_PATH)

        from internal.learning.trail_events import emit_rotation_tokens_snapshot

        emit_rotation_tokens_snapshot(tokens, changed)
        return changed
    except Exception as exc:
        logger.warning("rotation_tokens soul_map mirror failed: %s", exc)
        return False


def build_rotation_tokens_response() -> Dict[str, Any]:
    """Public shape for GET /api/rotation-tokens."""
    prices = fetch_rotation_token_prices()
    tokens: List[Dict[str, Any]] = []
    for symbol in ROTATION_TOKENS:
        entry = prices.get(symbol, {}) if isinstance(prices, dict) else {}
        price = entry.get("price")
        change = entry.get("price_change_24h")
        conviction = None
        if change is not None:
            conviction = min(95, max(5, 50 + int(float(change) * 2)))
        tokens.append(
            {
                "symbol": symbol.upper(),
                "name": symbol.title(),
                "price": price,
                "price_change_24h": change,
                "conviction": conviction,
                "source": "coingecko" if price is not None else "watchlist",
            }
        )
    _mirror_rotation_snapshot_to_soul_map(tokens)
    return {"status": "success", "tokens": tokens}
