"""Build Dev Pulse rows from registry github URLs + graded ledger snippets."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from internal.simivision.weighing_room import subnet_graded_snippet
from internal.subnet_names import name_for_netuid

_CACHE: Dict[str, Any] = {"at": 0.0, "payload": None}
_CACHE_TTL_SEC = 300.0


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _has_public_repo(github: Any) -> bool:
    if not isinstance(github, str):
        return False
    return bool(github.strip())


def _load_registry_subnets() -> List[Dict[str, Any]]:
    try:
        from server import _normalize_registry_subnet, load_data

        raw = load_data("config/registry.json")
        if not isinstance(raw, dict):
            return []
        return [_normalize_registry_subnet(s) for s in raw.values() if isinstance(s, dict)]
    except Exception:
        return []


def build_dev_radar_rows(subnets: List[Dict[str, Any]], *, limit: int = 128) -> List[Dict[str, Any]]:
    """Registry rows with repo risk flags and graded snippets."""
    rows: List[Dict[str, Any]] = []
    for sn in subnets:
        if not isinstance(sn, dict):
            continue
        netuid = sn.get("netuid", sn.get("id"))
        if netuid is None:
            continue
        try:
            nu = int(netuid)
        except (TypeError, ValueError):
            continue
        github = sn.get("github")
        has_repo = _has_public_repo(github)
        rows.append(
            {
                "netuid": nu,
                "name": sn.get("name") or name_for_netuid(nu),
                "github": github if has_repo else None,
                "has_public_repo": has_repo,
                "risk_flag": None if has_repo else "no_public_repo",
                "graded_snippet": subnet_graded_snippet(nu),
                "velocity_score": None,
                "emission": float(sn.get("emission") or 0),
            }
        )

    rows.sort(
        key=lambda r: (
            0 if r.get("has_public_repo") else 1,
            -(float(r.get("emission") or 0)),
            int(r.get("netuid") or 0),
        )
    )
    return rows[: max(1, min(int(limit), 256))]


def build_dev_radar_payload(*, limit: int = 128) -> Dict[str, Any]:
    """Full API payload (cached 5 min)."""
    now = time.monotonic()
    cached = _CACHE.get("payload")
    if isinstance(cached, dict) and now - float(_CACHE.get("at") or 0) < _CACHE_TTL_SEC:
        payload = dict(cached)
        subnets = list(payload.get("subnets") or [])
        payload["subnets"] = subnets[: max(1, min(int(limit), 256))]
        return payload

    subnets = _load_registry_subnets()
    if not subnets:
        return {
            "status": "success",
            "data_available": False,
            "source": "registry",
            "updated_at": _now_iso(),
            "summary": {"with_repo": 0, "without_repo": 0},
            "subnets": [],
            "message": "No registry economics — dev pulse warming up",
        }

    rows = build_dev_radar_rows(subnets, limit=256)
    with_repo = sum(1 for r in rows if r.get("has_public_repo"))
    without_repo = len(rows) - with_repo
    payload = {
        "status": "success",
        "data_available": True,
        "source": "registry",
        "updated_at": _now_iso(),
        "summary": {"with_repo": with_repo, "without_repo": without_repo},
        "subnets": rows,
    }
    _CACHE["at"] = now
    _CACHE["payload"] = payload
    out = dict(payload)
    out["subnets"] = rows[: max(1, min(int(limit), 256))]
    return out
