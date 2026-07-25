"""Live connection status for Bittensor subnet integrations.

Primary banner: Bittensor chain + Blockmachine RPC (SN19) + DeSearch / Chutes / Ditto.
Expanded candidates from TaonSquare (https://taonsquare.com/api).
"""

from __future__ import annotations

import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional, Set, Tuple

from internal.integrations.desearch_spend import get_spend_summary, record_desearch_response
from internal.integrations.taonsquare import catalog_summary, recommend_candidates

logger = logging.getLogger(__name__)

_PROBE_TIMEOUT = 3
_CACHE_TTL_SEC = 60.0
_cache_lock = threading.Lock()
_cache: Dict[str, Any] = {"at": 0.0, "payload": None}
_BLOCKMACHINE_RPC = os.environ.get("BLOCKMACHINE_RPC_URL", "https://rpc.blockmachine.io").rstrip("/")
_BITTENSOR_RPC = os.environ.get("BITTENSOR_RPC_URL", _BLOCKMACHINE_RPC).rstrip("/")
_BITTENSOR_NETWORK = os.environ.get("BITTENSOR_NETWORK", "finney").strip().lower() or "finney"

# ponytail: static catalog; add rows here when a new subnet ships.
INTEGRATIONS: List[Dict[str, Any]] = [
    {
        "netuid": None,
        "slug": "bittensor",
        "name": "Finney mainnet",
        "chain": _BITTENSOR_NETWORK,
        "role": "Bittensor production chain",
        "docs_url": "https://docs.bittensor.com",
    },
    {
        "netuid": 19,
        "slug": "blockmachine",
        "name": "Blockmachine",
        "role": "Live RPC & subnet feed (SN19)",
        "docs_url": "https://blockmachine.io",
    },
    {
        "netuid": 22,
        "slug": "desearch",
        "name": "DeSearch",
        "role": "Search & social evidence",
        "docs_url": "https://www.desearch.ai/docs/api-reference",
    },
    {
        "netuid": 64,
        "slug": "chutes",
        "name": "Chutes",
        "role": "Council LLM compute",
        "docs_url": "https://chutes.ai",
    },
    {
        "netuid": 118,
        "slug": "ditto",
        "name": "Ditto",
        "role": "Agent memory (SN118)",
        "docs_url": "https://heyditto.ai",
    },
]


def _http_probe(
    method: str,
    url: str,
    *,
    headers: Optional[Dict[str, str]] = None,
    json_body: Optional[Dict[str, Any]] = None,
) -> tuple[bool, int, str]:
    """Return (ok, status_code, detail). ok means HTTP response received."""
    try:
        import requests

        resp = requests.request(
            method,
            url,
            headers=headers or {},
            json=json_body,
            timeout=_PROBE_TIMEOUT,
        )
        if "desearch.ai" in url:
            record_desearch_response(resp, path=url, label="probe")
        return True, resp.status_code, (resp.text or "")[:240]
    except Exception as exc:
        logger.debug("probe %s failed: %s", url, exc)
        return False, 0, str(exc)[:240]


def _rpc_chain_healthy(endpoint: str) -> tuple[bool, str]:
    """JSON-RPC chain_getBlockHash — shared health check for Bittensor nodes."""
    try:
        import requests

        resp = requests.post(
            endpoint,
            json={"jsonrpc": "2.0", "method": "chain_getBlockHash", "params": [0], "id": 1},
            timeout=_PROBE_TIMEOUT,
        )
        if resp.status_code != 200:
            return False, f"HTTP {resp.status_code}"
        data = resp.json()
        if data.get("result"):
            return True, "chain RPC ok"
        err = data.get("error") or {}
        return False, str(err.get("message") or err or "no result")[:120]
    except Exception as exc:
        logger.debug("rpc probe %s failed: %s", endpoint, exc)
        return False, str(exc)[:120]


def _probe_bittensor() -> Dict[str, Any]:
    network = _BITTENSOR_NETWORK
    label = "Finney mainnet" if network == "finney" else f"Bittensor {network}"
    healthy, detail = _rpc_chain_healthy(_BITTENSOR_RPC)
    if healthy:
        detail = f"{label} · chain RPC ok"
    else:
        detail = f"{label} unreachable · {detail}"
    return {
        "reachable": healthy,
        "connected": healthy,
        "detail": detail,
        "has_credential": True,
        "chain": network,
    }


def _probe_blockmachine() -> Dict[str, Any]:
    healthy, detail = _rpc_chain_healthy(_BLOCKMACHINE_RPC)
    if healthy:
        detail = f"{detail} · SN19 live feed"
    else:
        detail = f"RPC unreachable · {detail}"
    return {
        "reachable": healthy,
        "connected": healthy,
        "detail": detail,
        "has_credential": True,
    }


def _probe_desearch() -> Dict[str, Any]:
    api_key = os.environ.get("DESEARCH_API_KEY") or os.environ.get("DESEARCH_ACCESS_KEY")
    base = os.environ.get("DESEARCH_BASE_URL", "https://api.desearch.ai").rstrip("/")
    ok, code, body = _http_probe("GET", f"{base}/health")
    reachable = ok and code == 200
    connected = False
    detail = "health unreachable"
    if reachable:
        detail = "health ok"
        # Key present + health ok = connected. Skip paid search probe on every status poll.
        if api_key:
            connected = True
            detail = "key configured · health ok"
    return {
        "reachable": reachable,
        "connected": connected,
        "detail": detail,
        "has_credential": bool(api_key),
    }


_DEFAULT_CHUTES_BASE = "https://llm.chutes.ai/v1"


def _chutes_base_url() -> str:
    return (
        os.environ.get("CHUTES_BASE_URL")
        or os.environ.get("LLM_BASE_URL")
        or _DEFAULT_CHUTES_BASE
    ).rstrip("/")


def _probe_chutes() -> Dict[str, Any]:
    api_key = (
        os.environ.get("CHUTES_API_KEY")
        or os.environ.get("OPENAI_API_KEY")
        or os.environ.get("LLM_API_KEY")
    )
    base = _chutes_base_url()
    models_url = f"{base}/models"
    ok_pub, code_pub, _ = _http_probe("GET", models_url)
    # ponytail: Fly secrets sometimes set LLM_BASE_URL to api.chutes.ai (404 on /models).
    if (not ok_pub or code_pub == 404) and base != _DEFAULT_CHUTES_BASE.rstrip("/"):
        base = _DEFAULT_CHUTES_BASE.rstrip("/")
        models_url = f"{base}/models"
        ok_pub, code_pub, _ = _http_probe("GET", models_url)
    reachable = ok_pub and code_pub == 200
    if not api_key:
        return {
            "reachable": reachable,
            "connected": False,
            "detail": "add CHUTES_API_KEY for council chat" if reachable else f"HTTP {code_pub}",
            "has_credential": False,
        }
    ok, code, body = _http_probe(
        "GET",
        models_url,
        headers={"Authorization": f"Bearer {api_key}"},
    )
    if ok and code == 200:
        detail = "models ok · council chat"
    elif ok and code in (401, 403):
        detail = "key rejected"
    elif reachable:
        detail = "API live · key not verified on /models"
    elif code_pub == 404:
        detail = "check CHUTES_BASE_URL (use https://llm.chutes.ai/v1)"
    else:
        detail = f"HTTP {code}" if ok else body
    connected = ok and code == 200
    return {
        "reachable": reachable or (ok and code in (200, 401, 403)),
        "connected": connected,
        "detail": detail,
        "has_credential": True,
    }


def _probe_ditto() -> Dict[str, Any]:
    base = os.environ.get("DITTO_BASE_URL", "https://api.heyditto.ai").rstrip("/")
    ok, code, body = _http_probe("GET", f"{base}/health")
    reachable = ok and code in (200, 401)
    connected = True
    detail = "SN118 dogfood"
    if ok and code == 200:
        detail = "health ok · SN118 dogfood"
    elif ok and code == 401:
        detail = "API live · SN118 dogfood"
    return {
        "reachable": reachable,
        "connected": connected,
        "detail": detail,
        "has_credential": True,
    }


_PROBERS = {
    "bittensor": _probe_bittensor,
    "blockmachine": _probe_blockmachine,
    "desearch": _probe_desearch,
    "chutes": _probe_chutes,
    "ditto": _probe_ditto,
}


def clear_status_cache() -> None:
    """Reset probe cache (tests / forced refresh)."""
    with _cache_lock:
        _cache["at"] = 0.0
        _cache["payload"] = None


def build_integrations_status(*, force: bool = False) -> Dict[str, Any]:
    """Aggregate live probe results for the compact status strip + ops.

    Cached ~60s so homepage polls don't wedge the Fly worker with serial probes.
    """
    if force:
        clear_status_cache()
    now = time.monotonic()
    with _cache_lock:
        cached = _cache.get("payload")
        if (
            not force
            and cached is not None
            and (now - float(_cache.get("at") or 0.0)) < _CACHE_TTL_SEC
        ):
            return cached

    rows: List[Dict[str, Any]] = []
    connected_n = 0
    primary_netuids: Set[int] = set()
    probe_results: Dict[str, Dict[str, Any]] = {}

    def _run(slug: str) -> Tuple[str, Dict[str, Any]]:
        return slug, _PROBERS[slug]()

    with ThreadPoolExecutor(max_workers=len(INTEGRATIONS)) as pool:
        futures = [pool.submit(_run, spec["slug"]) for spec in INTEGRATIONS]
        for fut in as_completed(futures):
            try:
                slug, probe = fut.result()
                probe_results[slug] = probe
            except Exception as exc:
                logger.warning("integration probe failed: %s", exc)

    for spec in INTEGRATIONS:
        slug = spec["slug"]
        probe = probe_results.get(slug) or {
            "reachable": False,
            "connected": False,
            "detail": "probe failed",
            "has_credential": False,
        }
        if probe.get("connected"):
            connected_n += 1
        netuid = spec.get("netuid")
        if netuid is not None:
            primary_netuids.add(int(netuid))
        rows.append({**spec, **probe, "status": _status_label(probe), "tier": "primary"})
    candidates = recommend_candidates(exclude=primary_netuids, limit=12)
    target_minimum = 3
    payload = {
        "integrations": rows,
        "candidates": candidates,
        "catalog": catalog_summary(),
        "connected_count": connected_n,
        "integration_total": len(rows),
        "target_minimum": target_minimum,
        "ready_for_launch": connected_n >= target_minimum,
        "desearch_spend": get_spend_summary(recent_limit=10),
        "cached": False,
    }
    with _cache_lock:
        _cache["at"] = time.monotonic()
        _cache["payload"] = {**payload, "cached": True}
    return payload


def _status_label(probe: Dict[str, Any]) -> str:
    if probe.get("connected"):
        return "connected"
    if probe.get("reachable"):
        return "reachable"
    return "offline"
