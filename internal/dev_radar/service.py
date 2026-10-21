"""Build Dev Pulse rows from registry github URLs + graded ledger snippets."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from internal.simivision.weighing_room import subnet_graded_snippet
from internal.subnet_names import name_for_netuid

_CACHE: Dict[str, Any] = {"at": 0.0, "payload": None}
_CACHE_TTL_SEC = 300.0
_GAP_SIGNAL_THRESHOLD = 60.0


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


def _percentile_rank(value: float, cohort: List[float]) -> Optional[float]:
    if not cohort:
        return None
    if len(cohort) == 1:
        return 100.0
    below = sum(1 for x in cohort if x < value)
    return round(100.0 * below / len(cohort), 1)


def _overlay_github_cache(rows: List[Dict[str, Any]]) -> str:
    try:
        from internal.dev_radar.github_sync import load_dev_radar_cache
    except Exception:
        return "registry"

    cache = load_dev_radar_cache()
    cached = cache.get("subnets") if isinstance(cache.get("subnets"), dict) else {}
    if not cached:
        return "registry"

    velocity_vals: List[float] = []
    price_vals: List[float] = []
    for row in rows:
        key = str(row.get("netuid"))
        overlay = cached.get(key) if isinstance(cached.get(key), dict) else {}
        if overlay.get("velocity_score") is not None:
            row["velocity_score"] = overlay.get("velocity_score")
            row["commits_7d"] = overlay.get("commits_7d")
            row["authors_7d"] = overlay.get("authors_7d")
            row["last_push_at"] = overlay.get("last_push_at")
            try:
                velocity_vals.append(float(row["velocity_score"]))
            except (TypeError, ValueError):
                pass
        price = row.get("price_change_24h")
        if price is not None:
            try:
                price_vals.append(abs(float(price)))
            except (TypeError, ValueError):
                pass

    for row in rows:
        vel = row.get("velocity_score")
        price = row.get("price_change_24h")
        if vel is None or price is None:
            row["gap_score"] = None
            row["gap_signal"] = None
            continue
        try:
            vel_f = float(vel)
            price_f = abs(float(price))
        except (TypeError, ValueError):
            row["gap_score"] = None
            row["gap_signal"] = None
            continue
        price_pct = _percentile_rank(price_f, price_vals) if price_vals else None
        if price_pct is None:
            row["gap_score"] = None
            row["gap_signal"] = None
            continue
        gap = round(vel_f - price_pct, 1)
        row["gap_score"] = gap
        row["gap_signal"] = "dev_ahead_of_price" if gap >= _GAP_SIGNAL_THRESHOLD else None

    return "registry+github" if any(r.get("velocity_score") is not None for r in rows) else "registry"


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
                "commits_7d": None,
                "authors_7d": None,
                "last_push_at": None,
                "gap_score": None,
                "gap_signal": None,
                "price_change_24h": sn.get("price_change_24h"),
                "emission": float(sn.get("emission") or 0),
            }
        )

    source = _overlay_github_cache(rows)
    rows.sort(
        key=lambda r: (
            0 if r.get("gap_signal") else 1,
            -(float(r.get("velocity_score") or 0)),
            0 if r.get("has_public_repo") else 1,
            -(float(r.get("emission") or 0)),
            int(r.get("netuid") or 0),
        )
    )
    # ponytail: source tag is returned via build_dev_radar_payload, not per-row
    _ = source
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

    all_rows = build_dev_radar_rows(subnets, limit=256)
    try:
        from internal.dev_radar.github_sync import load_dev_radar_cache

        cache = load_dev_radar_cache()
        source = "registry+github" if (cache.get("subnets") or {}) else "registry"
        if any(r.get("velocity_score") is not None for r in all_rows):
            source = "registry+github"
    except Exception:
        source = "registry"

    with_repo = sum(1 for r in all_rows if r.get("has_public_repo"))
    without_repo = len(all_rows) - with_repo
    gap_count = sum(1 for r in all_rows if r.get("gap_signal"))
    payload = {
        "status": "success",
        "data_available": True,
        "source": source,
        "updated_at": _now_iso(),
        "summary": {
            "with_repo": with_repo,
            "without_repo": without_repo,
            "gap_signals": gap_count,
        },
        "subnets": all_rows,
    }
    _CACHE["at"] = now
    _CACHE["payload"] = payload
    out = dict(payload)
    out["subnets"] = all_rows[: max(1, min(int(limit), 256))]
    return out
