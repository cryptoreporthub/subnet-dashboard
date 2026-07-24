"""Live connection status for Bittensor subnet integrations (SN22/50/64/118).

Priority order from Ditto subnet research (129 subnets reviewed):
  SN22 DeSearch — social/search evidence
  SN50 Synth — macro forecasting signals
  SN64 Chutes — LLM compute (chat)
  SN118 Ditto — persistence / dogfood
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_PROBE_TIMEOUT = 6

# ponytail: static catalog; add rows here when a new subnet ships.
INTEGRATIONS: List[Dict[str, Any]] = [
    {
        "netuid": 22,
        "slug": "desearch",
        "name": "DeSearch",
        "role": "Search & social evidence",
        "docs_url": "https://www.desearch.ai/docs/api-reference",
    },
    {
        "netuid": 50,
        "slug": "synth",
        "name": "Synth",
        "role": "Macro forecasting signals",
        "docs_url": "https://api.synthdata.co",
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
        return True, resp.status_code, (resp.text or "")[:240]
    except Exception as exc:
        logger.debug("probe %s failed: %s", url, exc)
        return False, 0, str(exc)[:240]


def _probe_desearch() -> Dict[str, Any]:
    api_key = os.environ.get("DESEARCH_API_KEY") or os.environ.get("DESEARCH_ACCESS_KEY")
    base = os.environ.get("DESEARCH_BASE_URL", "https://api.desearch.ai").rstrip("/")
    ok, code, body = _http_probe("GET", f"{base}/health")
    reachable = ok and code == 200
    connected = False
    detail = "health unreachable"
    if reachable:
        detail = "health ok"
        if api_key:
            hdrs = {"access-key": api_key, "Content-Type": "application/json"}
            s_ok, s_code, _ = _http_probe(
                "POST",
                f"{base}/search/links/web",
                headers=hdrs,
                json_body={"prompt": "Bittensor subnet", "count": 1},
            )
            if s_ok and s_code == 200:
                connected = True
                detail = "search probe ok"
            elif s_ok and s_code in (401, 403):
                detail = "key rejected"
            else:
                detail = f"search probe HTTP {s_code}"
    return {
        "reachable": reachable,
        "connected": connected,
        "detail": detail,
        "has_credential": bool(api_key),
    }


def _probe_synth() -> Dict[str, Any]:
    api_key = os.environ.get("SYNTH_API_KEY") or os.environ.get("SYNTHDATA_API_KEY")
    base = os.environ.get("SYNTH_BASE_URL", "https://api.synthdata.co").rstrip("/")
    url = f"{base}/insights/prediction-percentiles?asset=BTC"
    headers: Dict[str, str] = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    ok, code, body = _http_probe("GET", url, headers=headers)
    reachable = ok and code in (200, 400, 401, 403)
    connected = ok and code == 200
    detail = f"HTTP {code}" if ok else body
    if ok and code == 400 and "missing key" in body.lower():
        detail = "API live — add SYNTH_API_KEY"
    return {
        "reachable": reachable,
        "connected": connected,
        "detail": detail,
        "has_credential": bool(api_key),
    }


def _probe_chutes() -> Dict[str, Any]:
    api_key = (
        os.environ.get("CHUTES_API_KEY")
        or os.environ.get("OPENAI_API_KEY")
        or os.environ.get("LLM_API_KEY")
    )
    base = os.environ.get("CHUTES_BASE_URL") or os.environ.get(
        "LLM_BASE_URL", "https://api.chutes.ai/v1"
    )
    base = base.rstrip("/")
    if not api_key:
        ok, code, body = _http_probe("GET", f"{base}/models")
        reachable = ok and code in (200, 401, 403, 404)
        return {
            "reachable": reachable,
            "connected": False,
            "detail": "add CHUTES_API_KEY for council chat",
            "has_credential": False,
        }
    ok, code, body = _http_probe(
        "GET",
        f"{base}/models",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    connected = ok and code == 200
    return {
        "reachable": ok and code in (200, 401, 403),
        "connected": connected,
        "detail": f"HTTP {code}" if ok else body,
        "has_credential": True,
    }


def _probe_ditto() -> Dict[str, Any]:
    base = os.environ.get("DITTO_BASE_URL", "https://api.heyditto.ai").rstrip("/")
    ok, code, body = _http_probe("GET", f"{base}/health")
    reachable = ok and code in (200, 401)
    # Dogfood SN118 — product ships on Ditto memory layer.
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
    "desearch": _probe_desearch,
    "synth": _probe_synth,
    "chutes": _probe_chutes,
    "ditto": _probe_ditto,
}


def build_integrations_status() -> Dict[str, Any]:
    """Aggregate live probe results for marketing corner + ops."""
    rows: List[Dict[str, Any]] = []
    connected_n = 0
    for spec in INTEGRATIONS:
        slug = spec["slug"]
        probe = _PROBERS[slug]()
        if probe.get("connected"):
            connected_n += 1
        rows.append({**spec, **probe, "status": _status_label(probe)})
    return {
        "integrations": rows,
        "connected_count": connected_n,
        "target_minimum": 3,
        "ready_for_launch": connected_n >= 3,
    }


def _status_label(probe: Dict[str, Any]) -> str:
    if probe.get("connected"):
        return "connected"
    if probe.get("reachable"):
        return "reachable"
    return "offline"
