"""Macro mood signals from connected Bittensor subnet APIs."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from internal.integrations.status import _http_probe

logger = logging.getLogger(__name__)

_READYAI_SAMPLE = (
    "https://raw.githubusercontent.com/afterpartyai/llms_txt_store/master/com/s/t/r/i/p/e/llms.txt"
)


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _fetch_synth_btc() -> Optional[Dict[str, Any]]:
    api_key = os.environ.get("SYNTH_API_KEY") or os.environ.get("SYNTHDATA_API_KEY")
    if not api_key:
        return None
    base = os.environ.get("SYNTH_BASE_URL", "https://api.synthdata.co").rstrip("/")
    ok, code, body = _http_probe(
        "GET",
        f"{base}/insights/prediction-percentiles?asset=BTC",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    if not ok or code != 200:
        return None
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        data = {"raw": body[:200]}
    return {"netuid": 50, "slug": "synth", "kind": "btc_forecast", "data": data}


def _fetch_numinous_leaderboard() -> Optional[Dict[str, Any]]:
    ok, code, body = _http_probe(
        "GET",
        "https://api.numinouslabs.io/api/v1/leaderboard",
    )
    if not ok or code != 200:
        return None
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return None
    results = payload.get("results") or []
    top = results[0] if results else {}
    return {
        "netuid": 6,
        "slug": "numinous",
        "kind": "leaderboard",
        "data": {
            "miners": len(results),
            "top_miner_uid": top.get("miner_uid"),
            "top_weight": top.get("weight"),
        },
    }


def _fetch_desearch_snippet() -> Optional[Dict[str, Any]]:
    api_key = os.environ.get("DESEARCH_API_KEY") or os.environ.get("DESEARCH_ACCESS_KEY")
    if not api_key:
        return None
    base = os.environ.get("DESEARCH_BASE_URL", "https://api.desearch.ai").rstrip("/")
    ok, code, body = _http_probe(
        "POST",
        f"{base}/search/links/web",
        headers={"access-key": api_key, "Content-Type": "application/json"},
        json_body={"prompt": "Bittensor subnet market sentiment", "count": 3},
    )
    if not ok or code != 200:
        return None
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        data = {"raw": body[:300]}
    return {"netuid": 22, "slug": "desearch", "kind": "web_search", "data": data}


def _fetch_readyai_sample() -> Optional[Dict[str, Any]]:
    ok, code, body = _http_probe("GET", _READYAI_SAMPLE)
    if not ok or code != 200:
        return None
    lines = [ln.strip() for ln in body.splitlines() if ln.strip()][:5]
    return {
        "netuid": 33,
        "slug": "readyai",
        "kind": "llms_txt_sample",
        "data": {"domain": "stripe.com", "preview_lines": lines},
    }


def build_macro_signals() -> Dict[str, Any]:
    """Best-effort macro signals from connected subnets (no raise on partial failure)."""
    signals: List[Dict[str, Any]] = []
    for fn in (_fetch_synth_btc, _fetch_numinous_leaderboard, _fetch_desearch_snippet, _fetch_readyai_sample):
        try:
            row = fn()
            if row:
                signals.append(row)
        except Exception as exc:
            logger.debug("macro signal fetch failed: %s", exc)
    mood = "neutral"
    if any(s.get("slug") == "synth" for s in signals):
        mood = "forecast_available"
    elif any(s.get("slug") == "numinous" for s in signals):
        mood = "forecast_network_live"
    return {
        "updated_at": _utcnow(),
        "mood": mood,
        "signal_count": len(signals),
        "signals": signals,
    }
