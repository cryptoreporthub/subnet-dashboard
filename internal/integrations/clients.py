"""Thin HTTP clients for primary Bittensor subnet integrations (SN22/50/64/118).

All calls are optional: missing keys return None without raising.
"""

from __future__ import annotations

import hashlib
import logging
import os
import time
from typing import Any, Dict, List, Optional, Tuple

from internal.integrations.desearch_http import desearch_request

logger = logging.getLogger(__name__)

_DEFAULT_CHUTES_LLM_BASE = "https://llm.chutes.ai/v1"
_DEFAULT_THIRTY_SPOKES_BASE = "https://api.thirtyspokes.ai/v1"
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
    if not (os.environ.get("DESEARCH_API_KEY") or os.environ.get("DESEARCH_ACCESS_KEY")):
        return None
    label = name or f"SN{netuid}"
    query = f"Bittensor subnet {netuid} {label}"

    def _fetch():
        resp = desearch_request(
            "POST",
            "/desearch/ai/search/links/web",
            json_body={"prompt": query, "tools": ["web"], "count": 10},
            label=f"snippet:SN{netuid}",
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


def desearch_ai_summary(prompt: str, *, tools=None) -> Optional[Dict[str, Any]]:
    """AI Search summary + citations when key configured (cached 5m)."""
    if not (os.environ.get("DESEARCH_API_KEY") or os.environ.get("DESEARCH_ACCESS_KEY")):
        return None
    tool_list = tools or ["web", "twitter"]

    def _fetch():
        resp = desearch_request(
            "POST",
            "/desearch/ai/search",
            json_body={
                "prompt": prompt,
                "tools": tool_list,
                "count": 10,
                "streaming": False,
                "result_type": "LINKS_WITH_FINAL_SUMMARY",
            },
            timeout=30,
            label="ai_summary",
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
        if not isinstance(data, dict):
            return None
        completion = data.get("completion") if isinstance(data.get("completion"), dict) else data
        summary = (
            completion.get("search_summary")
            or completion.get("text")
            or data.get("search_summary")
            or ""
        )
        sources = completion.get("key_sources") or data.get("key_sources") or []
        if not summary and not sources:
            return None
        return {
            "summary": str(summary).strip()[:500],
            "sources": [
                {"text": s.get("text", ""), "url": s.get("url", "")}
                for s in sources[:5]
                if isinstance(s, dict)
            ],
        }

    key = hashlib.sha256(f"{prompt}:{','.join(tool_list)}".encode()).hexdigest()[:16]
    return _cached(f"desearch:ai:{key}", _fetch)


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


def chutes_llm_base_url() -> str:
    """OpenAI-compatible Chutes LLM base — normalizes stale api.chutes.ai Fly secrets."""
    base = (
        os.environ.get("CHUTES_BASE_URL")
        or os.environ.get("LLM_BASE_URL")
        or _DEFAULT_CHUTES_LLM_BASE
    ).rstrip("/")
    # ponytail: Fly often sets LLM_BASE_URL to api.chutes.ai (404 on /models and chat).
    if "api.chutes.ai" in base:
        return _DEFAULT_CHUTES_LLM_BASE.rstrip("/")
    return base


def chutes_configured() -> bool:
    """True when council chat can use Chutes (SN64)."""
    return bool(llm_api_key())


def llm_api_key() -> Optional[str]:
    return (
        os.environ.get("CHUTES_API_KEY")
        or os.environ.get("THIRTY_SPOKES_API_KEY")
        or os.environ.get("OPENAI_API_KEY")
        or os.environ.get("LLM_API_KEY")
    )


def thirty_spokes_base_url() -> str:
    return (
        os.environ.get("THIRTY_SPOKES_BASE_URL")
        or os.environ.get("THIRTY_SPOKES_API_BASE")
        or _DEFAULT_THIRTY_SPOKES_BASE
    ).rstrip("/")


def chutes_chat_model() -> str:
    """Chutes model id — ``default`` uses Chutes saved failover pool when unset."""
    return (
        os.environ.get("CHUTES_MODEL")
        or os.environ.get("LLM_MODEL")
        or "default"
    )


def thirty_spokes_chat_model() -> str:
    return os.environ.get("THIRTY_SPOKES_MODEL", "auto")


def _models_endpoint_ok(base: str, api_key: str) -> bool:
    """GET /models with bearer — mirrors integrations status probe."""

    def _check() -> bool:
        resp = _request(
            "GET",
            f"{base.rstrip('/')}/models",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=4,
        )
        return resp.status_code == 200

    key = f"models_ok:{base.rstrip('/')}"
    val = _cached(key, _check)
    return val is True


def clear_models_probe_cache() -> None:
    """Reset cached /models probes (tests)."""
    for key in list(_cache.keys()):
        if key.startswith("models_ok:"):
            del _cache[key]


def chat_llm_targets() -> List[Tuple[str, str, str]]:
    """Ordered (base_url, model, provider_slug) for chat completions — probe-aligned."""
    api_key = llm_api_key()
    if not api_key:
        return []
    chutes_base = chutes_llm_base_url()
    chutes_model = chutes_chat_model()
    ts_base = thirty_spokes_base_url()
    ts_model = thirty_spokes_chat_model()
    chutes_ok = _models_endpoint_ok(chutes_base, api_key)
    ts_ok = _models_endpoint_ok(ts_base, api_key)
    targets: List[Tuple[str, str, str]] = []
    if chutes_ok:
        targets.append((chutes_base, chutes_model, "chutes"))
    if ts_ok:
        targets.append((ts_base, ts_model, "thirty_spokes"))
    if not targets:
        targets.append((chutes_base, chutes_model, "chutes"))
        targets.append((ts_base, ts_model, "thirty_spokes"))
    return targets


def chutes_model_fallbacks(primary: str) -> List[str]:
    """Extra Chutes model ids when the configured one returns empty."""
    fallbacks: List[str] = []
    if primary != "default":
        fallbacks.append("default")
    legacy = "deepseek-ai/DeepSeek-V3.2-TEE"
    if primary not in {legacy, "default"}:
        fallbacks.append(legacy)
    return fallbacks
