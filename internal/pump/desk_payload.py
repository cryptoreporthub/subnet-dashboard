"""Pump desk payload — worker volume on split_v2 web, local ladder otherwise.

Resilience (2026-08-11, out-of-harness): the local ladder build does per-row
signal work for ~129 subnets on a 1-core VM, which previously blocked every
GET /api/pump-alerts into the route deadline and returned an EMPTY timeout
bucket ("Pump desk busy") — the dashboard then showed dead dashes while the
ladder was fine on disk. Now the payload short-circuits on the last healthy
persisted desk payload (written right here after each good build) and falls
back to it stale-flagged instead of ever returning an empty timeout.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_SNAPSHOT_FRESH_SECONDS = int(os.environ.get("PUMP_DESK_PAYLOAD_FRESH_SECONDS", "600"))
_ROW_STALE_SECONDS = int(os.environ.get("PUMP_ROW_STALE_SECONDS", str(6 * 3600)))


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _payload_path() -> str:
    return os.environ.get(
        "PUMP_DESK_PAYLOAD_PATH", os.path.join("data", "pump_desk", "latest_payload.json")
    )


def _persist_payload(payload: Dict[str, Any]) -> None:
    """Persist the last healthy desk payload so /api/pump-alerts never wedges."""
    try:
        if os.environ.get("PYTEST_CURRENT_TEST"):
            return
        path = _payload_path()
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path) or ".", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump({"captured_at": _utcnow_iso(), "pump_desk_payload": payload}, fh)
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
    except Exception as exc:
        logger.debug("pump desk payload persist failed: %s", exc)


def _load_persisted_payload() -> Optional[Dict[str, Any]]:
    """Read the last persisted desk payload (captured_at, pump_desk_payload)."""
    try:
        with open(_payload_path(), "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict) and isinstance(data.get("pump_desk_payload"), dict):
            return data
    except Exception:
        return None
    return None


def _iso_age_seconds(value: Any) -> Optional[float]:
    if not value:
        return None
    try:
        ts = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return max(0.0, time.time() - ts.timestamp())
    except Exception:
        return None


def attach_pump_freshness(
    payload: Dict[str, Any],
    *,
    handler_stale: bool = False,
) -> Dict[str, Any]:
    """Additive freshness — does not rename or replace existing status."""
    out = dict(payload)
    alerts = out.get("alerts") if isinstance(out.get("alerts"), list) else []
    ages: List[float] = []
    for alert in alerts:
        if not isinstance(alert, dict):
            continue
        for key in ("updated_at", "as_of", "generated_at", "captured_at"):
            age = _iso_age_seconds(alert.get(key))
            if age is not None:
                ages.append(age)
                break
    max_age = max(ages) if ages else None
    status = str(out.get("status") or "").lower()
    data_available = bool(alerts)
    if status in ("unavailable", "error") and not data_available:
        freshness, scope = "unavailable", "handler"
    elif max_age is not None and max_age > _ROW_STALE_SECONDS:
        freshness, scope = "stale", "rows"
    elif handler_stale or out.get("stale"):
        freshness, scope = "stale", "handler"
    elif not data_available and status in ("timeout", "error", "unavailable", "empty"):
        freshness, scope = "unavailable" if status != "empty" else "unavailable", "handler"
    else:
        freshness, scope = "fresh", "rows" if data_available else "handler"
    out.setdefault("generated_at", _utcnow_iso())
    out["max_row_age_seconds"] = None if max_age is None else int(max_age)
    out["data_available"] = data_available
    out["freshness"] = freshness
    out["freshness_scope"] = scope
    return out


def _mark_stale(payload: Dict[str, Any], captured_at: str) -> Dict[str, Any]:
    out = dict(payload)
    out["stale"] = True
    out["stale_captured_at"] = str(captured_at or "")
    prior = str(out.get("status") or "")
    if prior.lower() in ("", "timeout", "error", "unavailable"):
        out["prior_status"] = prior or "unavailable"
        out["status"] = "ok"
    out.pop("empty_message", None)
    return attach_pump_freshness(out, handler_stale=True)


def _local_pump_alerts_desk(
    subnets: Optional[List[Dict[str, Any]]],
    *,
    subnet_timeout: float,
) -> Dict[str, Any]:
    from internal.learning.pump_alert import build_pump_alerts_desk

    rows = subnets if subnets is not None else []
    return build_pump_alerts_desk(rows)


def load_pump_alerts_desk_payload(
    subnets: Optional[List[Dict[str, Any]]] = None,
    *,
    subnet_timeout: float = 4.0,
) -> Dict[str, Any]:
    """Desk JSON for SSR, /pump, and internal probes — matches GET /api/pump-alerts on worker.

    Resilience order:
      1. worker volume proxy (split_v2 only)
      2. fresh persisted desk payload (fast short-circuit, no build)
      3. live local build (persists the healthy payload for next time)
      4. last-known-good payload, stale-flagged — never an empty timeout bucket
    """
    try:
        from internal.data_volume import needs_worker_volume_proxy

        if needs_worker_volume_proxy():
            from internal.worker_proxy import fetch_worker_json_sync

            remote = fetch_worker_json_sync("/api/pump-alerts")
            if isinstance(remote, dict) and remote.get("error") != "worker_volume_proxy_failed":
                status = str(remote.get("status") or "").lower()
                if status not in ("error", "unavailable"):
                    return attach_pump_freshness(remote)
    except Exception as exc:
        logger.warning("pump desk worker fetch failed, using local ladder: %s", exc)

    persisted = _load_persisted_payload()
    if persisted is not None:
        captured = persisted.get("captured_at") or ""
        try:
            age = time.time() - datetime.fromisoformat(str(captured).replace("Z", "+00:00")).timestamp()
        except Exception:
            age = float("inf")
        if age <= _SNAPSHOT_FRESH_SECONDS:
            return attach_pump_freshness(persisted["pump_desk_payload"])

    try:
        local = _local_pump_alerts_desk(subnets, subnet_timeout=subnet_timeout)
        if str(local.get("status") or "").lower() not in ("timeout", "error", "unavailable"):
            _persist_payload(local)
        return attach_pump_freshness(local)
    except Exception as exc:
        logger.warning("pump desk local build failed, serving last-known-good: %s", exc)

    if persisted is not None:
        return _mark_stale(persisted["pump_desk_payload"], persisted.get("captured_at"))

    return attach_pump_freshness(
        _local_pump_alerts_desk(subnets, subnet_timeout=subnet_timeout)
    )
