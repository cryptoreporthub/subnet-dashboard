"""Thin HTTP clients for primary Bittensor subnet integrations (SN22/50/64/118).

All calls are optional: missing keys return None without raising.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_CACHE_TTL = 300
_cache: Dict[str, Dict[str, Any]] = {}


def _cached(key: str, factory):
    now = time.time()
    row = _cache.get(key)
    if row and now - row.get("at", 0) < _CACHE_TTL:
        return row.get("value")
    try:
        value = factory()
    except Exception as exc:
        logger.debug("integration client %s failed: %s", key, exc)
        value = None
    _cache[key] = {"at": now, "value": value}
    return value


def _request(method: str, url: str, *, headers=None, json_body=None, timeout: int = 8):
    import requests

    return requests.request(
        method,
        url,
        headers=headers or {},
        json=json_body,
        timeout=timeout,
    )


def desearch_subnet_snippet(netuid: int, name: str = "") -> Optional[str]:
    """One-line social/web snippet for evidence layer (SN22)."""
    api_key = os.environ.get("DESEARCH_API_KEY") or os.environ.get("DESEARCH_ACCESS_KEY")
    if not api_key:
        return None
    base = os.environ.get("DESEARCH_BASE_URL", "https://api.desearch.ai").rstrip("/")
    label = name or f"SN{netuid}"
    query = f"Bittensor subnet {netuid} {label}"

    def _fetch():
        resp = _request(
            "POST",
            f"{base}/search/links/web",
            headers={"access-key": api_key, "Content-Type": "application/json"},
            json_body={"prompt": query, "count": 1},
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
        items = data if isinstance(data, list) else (data.get("data") or data.get("results") or [])
        if not items:
            return None
        first = items[0] if isinstance(items[0], dict) else {}
        title = str(first.get("title") or first.get("snippet") or first.get("description") or "").strip()
        return title[:120] if title else None

    return _cached(f"desearch:{netuid}", _fetch)


def synth_macro_skew(asset: str = "BTC", *, horizon: str = "24h") -> Optional[Dict[str, Any]]:
    """Macro forecast skew from Synth (SN50) — not per-subnet; tape context."""
    api_key = os.environ.get("SYNTH_API_KEY") or os.environ.get("SYNTHDATA_API_KEY")
    if not api_key:
        return None
    base = os.environ.get("SYNTH_BASE_URL", "https://api.synthdata.co").rstrip("/")

    def _fetch():
        hdrs = {"Authorization": f"Apikey {api_key}"}
        url = f"{base}/insights/prediction-percentiles?asset={asset}&horizon={horizon}"
        resp = _request("GET", url, headers=hdrs, timeout=10)
        if resp.status_code != 200:
            return None
        data = resp.json()
        if not isinstance(data, dict):
            return None
        median = data.get("median") or data.get("p50") or data.get("percentile_50")
        if median is None and isinstance(data.get("percentiles"), dict):
            median = data["percentiles"].get("50") or data["percentiles"].get("p50")
        if median is None:
            return None
        try:
            pct = float(median)
        except (TypeError, ValueError):
            return None
        direction = "up" if pct > 0.15 else "down" if pct < -0.15 else "flat"
        return {
            "asset": asset,
            "horizon": horizon,
            "median_pct": round(pct, 2),
            "direction": direction,
            "source": "synth",
        }

    return _cached(f"synth:{asset}:{horizon}", _fetch)


def chutes_configured() -> bool:
    """True when council chat can use Chutes (SN64)."""
    return bool(
        os.environ.get("CHUTES_API_KEY")
        or os.environ.get("OPENAI_API_KEY")
        or os.environ.get("LLM_API_KEY")
    )
