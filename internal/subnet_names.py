"""Canonical subnet name resolution — single source for all API/UI paths."""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

REGISTRY_PATH = os.environ.get("REGISTRY_PATH", "config/registry.json")
OVERRIDES_PATH = os.environ.get("SUBNET_NAME_OVERRIDES_PATH", "config/subnet_name_overrides.json")
REMOTE_REGISTRY_URL = os.environ.get(
    "REMOTE_REGISTRY_URL",
    "https://raw.githubusercontent.com/taostat/subnets-infos/main/subnets.json",
)
_BAD_NAMES = frozenset({"", "unknown", "deprecated", "none", "unnamed", "snnone"})
_CACHE_TTL_SECONDS = int(os.environ.get("SUBNET_NAMES_CACHE_TTL", "300"))

_lock = threading.Lock()
_remote_cache: Dict[str, Any] = {"at": 0.0, "data": {}}
_identity_cache: Dict[int, Dict[str, Any]] = {}


def _is_bad_name(name: Any) -> bool:
    return not name or str(name).strip().lower() in _BAD_NAMES


def _netuid_key(row: Dict[str, Any]) -> Optional[int]:
    for k in ("netuid", "id", "subnet_id"):
        v = row.get(k)
        if v is None:
            continue
        try:
            return int(v)
        except (TypeError, ValueError):
            continue
    return None


def _load_local_registry() -> Dict[str, Any]:
    try:
        with open(REGISTRY_PATH, "r") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


_override_cache: Dict[str, Any] = {"at": 0.0, "data": {}}


def _load_name_overrides() -> Dict[str, str]:
    """Curator corrections when on-chain / taostat identity is stale or a meme placeholder."""
    now = time.time()
    with _lock:
        if now - float(_override_cache.get("at") or 0) < _CACHE_TTL_SECONDS:
            cached = _override_cache.get("data")
            if isinstance(cached, dict):
                return cached
    try:
        with open(OVERRIDES_PATH, "r") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            out: Dict[str, str] = {}
        else:
            out = {str(k): str(v).strip() for k, v in data.items() if v and str(v).strip()}
    except Exception:
        out = {}
    with _lock:
        _override_cache["at"] = now
        _override_cache["data"] = out
    return out


def _remote_registry() -> Dict[str, Any]:
    now = time.time()
    with _lock:
        if now - float(_remote_cache.get("at") or 0) < _CACHE_TTL_SECONDS:
            cached = _remote_cache.get("data")
            if isinstance(cached, dict):
                return cached
    try:
        resp = requests.get(REMOTE_REGISTRY_URL, timeout=4)
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, dict):
            with _lock:
                _remote_cache["at"] = now
                _remote_cache["data"] = data
            return data
    except Exception as exc:
        logger.debug("remote registry fetch failed: %s", exc)
    with _lock:
        cached = _remote_cache.get("data")
        return cached if isinstance(cached, dict) else {}


def _taostats_identity(netuid: int) -> Optional[str]:
    cached = _identity_cache.get(netuid)
    if cached and time.time() - cached.get("at", 0) < _CACHE_TTL_SECONDS:
        return cached.get("name")
    try:
        from fetchers.taostats_client import get_subnet_identity

        payload = get_subnet_identity(netuid)
        name = None
        if isinstance(payload, dict):
            records = payload.get("data") or payload.get("results") or [payload]
            if records and isinstance(records, list):
                row = records[0] if isinstance(records[0], dict) else {}
                name = row.get("name") or row.get("subnet_name") or row.get("identity")
        if name and not _is_bad_name(name):
            _identity_cache[netuid] = {"at": time.time(), "name": str(name)}
            return str(name)
    except Exception as exc:
        logger.debug("taostats identity for SN%d failed: %s", netuid, exc)
    return None


def resolve_subnet_name(
    netuid: int,
    *,
    local: Optional[Dict[str, Any]] = None,
    remote: Optional[Dict[str, Any]] = None,
    tmc_name: Optional[str] = None,
    use_taostats: bool = True,
) -> str:
    """Priority: curator override → taostat remote → TaoStats identity → local → TMC → SN{n}."""
    if netuid is None:
        return "SN?"
    try:
        n = int(netuid)
    except (TypeError, ValueError):
        return "SN?"

    override = _load_name_overrides().get(str(n))
    if override and not _is_bad_name(override):
        return override

    remote = remote if remote is not None else _remote_registry()
    remote_item = remote.get(str(n)) if isinstance(remote, dict) else None
    if isinstance(remote_item, dict):
        rname = remote_item.get("name")
        if not _is_bad_name(rname):
            return str(rname).strip()

    if use_taostats:
        ts_name = _taostats_identity(n)
        if ts_name:
            return ts_name

    local = local if local is not None else _load_local_registry()
    local_item = local.get(str(n)) if isinstance(local, dict) else None
    if isinstance(local_item, dict):
        lname = local_item.get("name")
        if not _is_bad_name(lname):
            return str(lname).strip()

    if tmc_name and not _is_bad_name(tmc_name):
        cleaned = str(tmc_name).strip()
        if cleaned.lower() != "snnone" and not cleaned.startswith("SNNone"):
            return cleaned

    return f"SN{n}"


def enrich_subnet_row(row: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
    """Return a copy with canonical ``name`` (and ``symbol`` when missing)."""
    out = dict(row)
    netuid = _netuid_key(out)
    if netuid is None:
        return out
    out["netuid"] = netuid
    tmc_name = kwargs.get("tmc_name", out.get("name"))
    resolved = resolve_subnet_name(netuid, tmc_name=tmc_name, **kwargs)
    if str(resolved).lower() in {"snnone", "none"} or resolved.startswith("SNNone"):
        resolved = f"SN{netuid}"
    out["name"] = resolved
    if not out.get("symbol"):
        out["symbol"] = str(out["name"])[:6].upper() if out["name"] else f"SN{netuid}"
    return out


def enrich_subnet_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    local = _load_local_registry()
    remote = _remote_registry()
    return [
        enrich_subnet_row(r, local=local, remote=remote, use_taostats=False)
        for r in (rows or [])
    ]


def enrich_subnet_rows_live(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Like enrich_subnet_rows but may call TaoStats identity (slower)."""
    local = _load_local_registry()
    remote = _remote_registry()
    return [
        enrich_subnet_row(r, local=local, remote=remote, use_taostats=True)
        for r in (rows or [])
    ]


def name_for_netuid(netuid: Any, *, use_taostats: bool = False) -> str:
    try:
        return resolve_subnet_name(int(netuid), use_taostats=use_taostats)
    except (TypeError, ValueError):
        return "SN?"


def canonical_subnet_display(sn: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Return netuid/name/symbol with canonical name resolution (picks, horizon, shortlist)."""
    if not isinstance(sn, dict):
        return None
    netuid = sn.get("netuid")
    if netuid is None:
        netuid = sn.get("id")
    if netuid is None:
        return None
    try:
        row = enrich_subnet_row(
            {"netuid": int(netuid), "name": sn.get("name"), "symbol": sn.get("symbol")},
            use_taostats=False,
        )
    except Exception:
        row = {"netuid": int(netuid), "name": name_for_netuid(netuid), "symbol": sn.get("symbol")}
    return {
        "netuid": row.get("netuid"),
        "name": row.get("name"),
        "symbol": row.get("symbol"),
    }


def refresh_daily_pick_names(payload: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Re-resolve pick/candidate subnet names from netuid (stale TMC/cache labels)."""
    base = dict(payload) if isinstance(payload, dict) else {}
    for key in ("pick", "candidate"):
        block = base.get(key)
        if not isinstance(block, dict):
            continue
        sn = block.get("subnet")
        if not isinstance(sn, dict):
            continue
        canon = canonical_subnet_display(sn)
        if not canon:
            continue
        updated = dict(block)
        updated["subnet"] = {**sn, **canon}
        base[key] = updated

    hv = base.get("horizon_views")
    if isinstance(hv, dict) and isinstance(hv.get("views"), dict):
        views = dict(hv["views"])
        for chip_id, view in views.items():
            if not isinstance(view, dict):
                continue
            sn = view.get("subnet")
            if not isinstance(sn, dict):
                continue
            canon = canonical_subnet_display(sn)
            if not canon:
                continue
            views[chip_id] = {**view, "subnet": {**sn, **canon}}
        base["horizon_views"] = {**hv, "views": views}
    return base


def refresh_stored_names(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Re-resolve ``name`` from netuid on read for persisted predictions/signals/trail rows."""
    out: List[Dict[str, Any]] = []
    for row in rows or []:
        if not isinstance(row, dict):
            out.append(row)
            continue
        item = dict(row)
        netuid = item.get("netuid")
        if netuid is None:
            netuid = item.get("subnet_id") or item.get("id")
        if netuid is not None:
            item["name"] = name_for_netuid(netuid, use_taostats=False)
        subnet = item.get("subnet")
        if isinstance(subnet, dict) and subnet.get("netuid") is not None:
            sub = dict(subnet)
            sub["name"] = name_for_netuid(sub["netuid"], use_taostats=False)
            item["subnet"] = sub
        out.append(item)
    return out
