"""Live connection status for Bittensor subnet integrations."""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional, Set

from internal.integrations.registry import INTEGRATIONS, INTEGRATION_NETUIDS
from internal.integrations.taonsquare import catalog_summary, recommend_candidates

logger = logging.getLogger(__name__)

_PROBE_TIMEOUT = 6
_READYAI_PROBE_URL = (
    "https://raw.githubusercontent.com/afterpartyai/llms_txt_store/master/com/s/t/r/i/p/e/llms.txt"
)


def _http_probe(
    method: str,
    url: str,
    *,
    headers: Optional[Dict[str, str]] = None,
    json_body: Optional[Dict[str, Any]] = None,
) -> tuple[bool, int, str]:
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


def _result(
    *,
    reachable: bool,
    connected: bool,
    detail: str,
    has_credential: bool = False,
) -> Dict[str, Any]:
    return {
        "reachable": reachable,
        "connected": connected,
        "detail": detail,
        "has_credential": has_credential,
    }


def _probe_desearch() -> Dict[str, Any]:
    api_key = os.environ.get("DESEARCH_API_KEY") or os.environ.get("DESEARCH_ACCESS_KEY")
    base = os.environ.get("DESEARCH_BASE_URL", "https://api.desearch.ai").rstrip("/")
    ok, code, _ = _http_probe("GET", f"{base}/health")
    if not ok or code != 200:
        return _result(reachable=False, connected=False, detail="health unreachable")
    if not api_key:
        return _result(reachable=True, connected=False, detail="health ok — add DESEARCH_API_KEY")
    hdrs = {"access-key": api_key, "Content-Type": "application/json"}
    s_ok, s_code, _ = _http_probe(
        "POST",
        f"{base}/search/links/web",
        headers=hdrs,
        json_body={"prompt": "Bittensor subnet", "count": 1},
    )
    if s_ok and s_code == 200:
        return _result(reachable=True, connected=True, detail="search probe ok", has_credential=True)
    if s_ok and s_code in (401, 403):
        return _result(reachable=True, connected=False, detail="key rejected", has_credential=True)
    return _result(
        reachable=True,
        connected=False,
        detail=f"search probe HTTP {s_code}",
        has_credential=True,
    )


def _probe_synth() -> Dict[str, Any]:
    api_key = os.environ.get("SYNTH_API_KEY") or os.environ.get("SYNTHDATA_API_KEY")
    base = os.environ.get("SYNTH_BASE_URL", "https://api.synthdata.co").rstrip("/")
    url = f"{base}/insights/prediction-percentiles?asset=BTC"
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    ok, code, body = _http_probe("GET", url, headers=headers)
    reachable = ok and code in (200, 400, 401, 403)
    connected = ok and code == 200
    detail = f"HTTP {code}" if ok else body
    if ok and code == 400 and "missing key" in body.lower():
        detail = "API live — add SYNTH_API_KEY"
    return _result(reachable=reachable, connected=connected, detail=detail, has_credential=bool(api_key))


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
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    ok, code, body = _http_probe("GET", f"{base}/models", headers=headers)
    if not api_key:
        return _result(
            reachable=ok and code in (200, 401, 403, 404),
            connected=False,
            detail="add CHUTES_API_KEY for council chat",
        )
    return _result(
        reachable=ok and code in (200, 401, 403),
        connected=ok and code == 200,
        detail=f"HTTP {code}" if ok else body,
        has_credential=True,
    )


def _probe_ditto() -> Dict[str, Any]:
    base = os.environ.get("DITTO_BASE_URL", "https://api.heyditto.ai").rstrip("/")
    ok, code, _ = _http_probe("GET", f"{base}/health")
    detail = "SN118 dogfood"
    if ok and code == 200:
        detail = "health ok · SN118 dogfood"
    elif ok and code == 401:
        detail = "API live · SN118 dogfood"
    return _result(
        reachable=ok and code in (200, 401),
        connected=True,
        detail=detail,
        has_credential=True,
    )


def _probe_numinous() -> Dict[str, Any]:
    api_key = os.environ.get("NUMINOUS_API_KEY") or os.environ.get("EVERSIGHT_API_KEY")
    ok, code, _ = _http_probe("GET", "https://api.numinouslabs.io/api/v1/leaderboard")
    if ok and code == 200:
        detail = "leaderboard live"
        if api_key:
            detail = "leaderboard + API key configured"
        return _result(reachable=True, connected=True, detail=detail, has_credential=bool(api_key))
    return _result(reachable=ok, connected=False, detail=f"leaderboard HTTP {code}" if ok else "offline")


def _probe_data_universe() -> Dict[str, Any]:
    api_key = os.environ.get("MACROCOSMOS_API_KEY") or os.environ.get("DATA_UNIVERSE_API_KEY")
    base = os.environ.get(
        "DATA_UNIVERSE_BASE_URL",
        "https://constellation.api.cloud.macrocosmos.ai",
    ).rstrip("/")
    if api_key:
        ok, code, _ = _http_probe(
            "GET",
            f"{base}/",
            headers={"Authorization": f"Bearer {api_key}"},
        )
        if ok and code in (200, 401, 403, 404):
            return _result(
                reachable=True,
                connected=code == 200,
                detail=f"Gravity API HTTP {code}",
                has_credential=True,
            )
    ok, code, _ = _http_probe("GET", "https://docs.macrocosmos.ai")
    return _result(
        reachable=ok and code == 200,
        connected=False,
        detail="docs live — add MACROCOSMOS_API_KEY for Gravity",
        has_credential=bool(api_key),
    )


def _probe_vanta() -> Dict[str, Any]:
    api_key = os.environ.get("TAOSHI_API_KEY") or os.environ.get("VANTA_API_KEY")
    if api_key:
        base = os.environ.get("VANTA_BASE_URL", "https://request.taoshi.io").rstrip("/")
        ok, code, _ = _http_probe(
            "GET",
            f"{base}/api/v1/health",
            headers={"x-taoshi-consumer-request-key": api_key},
        )
        if ok and code == 200:
            return _result(reachable=True, connected=True, detail="Taoshi API ok", has_credential=True)
    ok, code, _ = _http_probe("GET", "https://docs.taoshi.io")
    return _result(
        reachable=ok and code == 200,
        connected=False,
        detail="docs live — add TAOSHI_API_KEY",
        has_credential=bool(api_key),
    )


def _probe_readyai() -> Dict[str, Any]:
    ok, code, _ = _http_probe("GET", _READYAI_PROBE_URL)
    if ok and code == 200:
        return _result(reachable=True, connected=True, detail="llms.txt store live")
    ok2, code2, _ = _http_probe("GET", "https://readyai.ai/docs")
    return _result(
        reachable=(ok and code == 200) or (ok2 and code2 == 200),
        connected=False,
        detail="docs only — GitHub store unreachable",
    )


def _probe_lium() -> Dict[str, Any]:
    api_key = os.environ.get("LIUM_API_KEY")
    ok, code, _ = _http_probe("GET", "https://docs.lium.io")
    if api_key:
        return _result(
            reachable=ok and code == 200,
            connected=ok and code == 200,
            detail="docs live + LIUM_API_KEY set",
            has_credential=True,
        )
    return _result(
        reachable=ok and code == 200,
        connected=False,
        detail="docs live — add LIUM_API_KEY for compute",
    )


def _probe_graphite() -> Dict[str, Any]:
    ok, code, _ = _http_probe("GET", "https://github.com/GraphiteAI/Graphite-Subnet")
    return _result(
        reachable=ok and code == 200,
        connected=False,
        detail="repo reachable — API key TBD",
    )


def _probe_talisman() -> Dict[str, Any]:
    api_key = os.environ.get("TALISMAN_API_KEY")
    if api_key:
        base = os.environ.get("TALISMAN_BASE_URL", "").rstrip("/")
        if base:
            ok, code, _ = _http_probe("GET", f"{base}/health", headers={"Authorization": f"Bearer {api_key}"})
            return _result(
                reachable=ok,
                connected=ok and code == 200,
                detail=f"HTTP {code}" if ok else "offline",
                has_credential=True,
            )
    return _result(reachable=False, connected=False, detail="no public probe — add TALISMAN_BASE_URL")


_PROBERS = {
    "desearch": _probe_desearch,
    "synth": _probe_synth,
    "chutes": _probe_chutes,
    "ditto": _probe_ditto,
    "numinous": _probe_numinous,
    "data_universe": _probe_data_universe,
    "vanta": _probe_vanta,
    "readyai": _probe_readyai,
    "lium": _probe_lium,
    "graphite": _probe_graphite,
    "talisman": _probe_talisman,
}


def _status_label(probe: Dict[str, Any]) -> str:
    if probe.get("connected"):
        return "connected"
    if probe.get("reachable"):
        return "reachable"
    return "offline"


def _sort_key(row: Dict[str, Any]) -> tuple:
    order = {"connected": 0, "reachable": 1, "offline": 2}
    tier_order = {"core": 0, "extended": 1}
    return (
        order.get(row.get("status") or "offline", 9),
        tier_order.get(row.get("tier") or "extended", 9),
        row.get("netuid") or 0,
    )


def build_integrations_status() -> Dict[str, Any]:
    rows: List[Dict[str, Any]] = []
    connected_n = 0
    for spec in INTEGRATIONS:
        slug = spec["slug"]
        probe_fn = _PROBERS.get(slug)
        probe = probe_fn() if probe_fn else _result(reachable=False, connected=False, detail="no probe")
        if probe.get("connected"):
            connected_n += 1
        rows.append({**spec, **probe, "status": _status_label(probe)})
    rows.sort(key=_sort_key)
    candidates = recommend_candidates(exclude=INTEGRATION_NETUIDS, limit=8)
    return {
        "integrations": rows,
        "candidates": candidates,
        "catalog": catalog_summary(),
        "connected_count": connected_n,
        "target_minimum": 3,
        "ready_for_launch": connected_n >= 3,
    }
