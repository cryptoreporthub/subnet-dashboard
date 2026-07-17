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
REMOTE_REGISTRY_URL = os.environ.get(
    "REMOTE_REGISTRY_URL",
    "https://raw.githubusercontent.com/taostat/subnets-infos/main/subnets.json",
)
_BAD_NAMES = frozenset({"", "unknown", "deprecated", "none", "unnamed"})
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


def _remote_registry() -> Dict[str, Any]:
    now = time.time()
    with _lock:
        if now - float(_remote_cache.get("at") or 0) < _CACHE_TTL_SECONDS:
            cached = _remote_cache.get("data")
            if isinstance(cached, dict):
                return cached
    try:
        resp = requests.get(REMOTE_REGISTRY_URL, timeout=20)
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
    """Priority: taostat remote → TaoStats identity → local registry → TMC → SN{n}."""
    if netuid is None:
        return "SN?"
    try:
        n = int(netuid)
    except (TypeError, ValueError):
        return "SN?"

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
        return str(tmc_name).strip()

    return f"SN{n}"


def enrich_subnet_row(row: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
    """Return a copy with canonical ``name`` (and ``symbol`` when missing)."""
    out = dict(row)
    netuid = _netuid_key(out)
    if netuid is None:
        return out
    out["netuid"] = netuid
    tmc_name = kwargs.get("tmc_name", out.get("name"))
    out["name"] = resolve_subnet_name(netuid, tmc_name=tmc_name, **kwargs)
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
