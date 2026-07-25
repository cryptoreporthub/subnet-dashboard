"""Track DeSearch API spend from X-Desearch-* response headers."""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_MAX_RECENT = int(os.environ.get("DESEARCH_SPEND_RECENT_MAX", "100"))
_lock = threading.Lock()


def _state_path() -> str:
    return os.environ.get("DESEARCH_SPEND_PATH", "data/desearch_spend.json")


def parse_billing_headers(headers: Any) -> Dict[str, Any]:
    """Extract billing fields from response headers (case-insensitive)."""
    if headers is None:
        return {}
    get = headers.get if hasattr(headers, "get") else lambda _k, _d=None: None
    # requests headers are case-insensitive; normalize keys we care about.
    norm = {str(k).lower(): v for k, v in headers.items()} if hasattr(headers, "items") else {}

    def _hdr(*names: str) -> Optional[str]:
        for name in names:
            val = norm.get(name.lower())
            if val is not None and str(val).strip() != "":
                return str(val).strip()
        return None

    cost_raw = _hdr("x-desearch-cost-usd")
    usage_raw = _hdr("x-desearch-usage-count")
    out: Dict[str, Any] = {
        "service": _hdr("x-desearch-service"),
        "currency": _hdr("x-desearch-currency") or "USD",
    }
    if cost_raw is not None:
        try:
            out["cost_usd"] = round(float(cost_raw), 8)
        except (TypeError, ValueError):
            pass
    if usage_raw is not None:
        try:
            out["usage_count"] = int(float(usage_raw))
        except (TypeError, ValueError):
            pass
    return out


def _empty_state() -> Dict[str, Any]:
    return {
        "total_usd": 0.0,
        "total_items": 0,
        "calls": 0,
        "billable_calls": 0,
        "by_service": {},
        "recent": [],
        "updated_at": None,
    }


def _load_state() -> Dict[str, Any]:
    path = _state_path()
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            data.setdefault("by_service", {})
            data.setdefault("recent", [])
            return data
    except FileNotFoundError:
        pass
    except Exception as exc:
        logger.debug("desearch spend load failed: %s", exc)
    return _empty_state()


def _save_state(state: Dict[str, Any]) -> None:
    path = _state_path()
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        tmp = f"{path}.tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(state, fh, indent=2)
        os.replace(tmp, path)
    except Exception as exc:
        logger.debug("desearch spend save failed: %s", exc)


def record_desearch_response(
    resp: Any,
    *,
    path: str = "",
    label: str = "",
) -> Optional[Dict[str, Any]]:
    """Parse billing headers and append to rolling spend ledger. Returns billing dict if present."""
    if resp is None:
        return None
    billing = parse_billing_headers(getattr(resp, "headers", None))
    if billing.get("cost_usd") is None and billing.get("usage_count") is None:
        return None

    entry = {
        "at": datetime.now(timezone.utc).isoformat(),
        "path": (path or getattr(resp, "url", "") or "")[:240],
        "label": (label or "")[:80],
        "status_code": getattr(resp, "status_code", None),
        **billing,
    }
    cost = float(billing.get("cost_usd") or 0.0)
    items = int(billing.get("usage_count") or 0)
    service = str(billing.get("service") or "unknown")

    with _lock:
        state = _load_state()
        state["total_usd"] = round(float(state.get("total_usd") or 0.0) + cost, 8)
        state["total_items"] = int(state.get("total_items") or 0) + items
        state["calls"] = int(state.get("calls") or 0) + 1
        if cost > 0 or items > 0:
            state["billable_calls"] = int(state.get("billable_calls") or 0) + 1
        by_svc = state.setdefault("by_service", {})
        by_svc[service] = round(float(by_svc.get(service) or 0.0) + cost, 8)
        recent: List[Dict[str, Any]] = list(state.get("recent") or [])
        recent.append(entry)
        state["recent"] = recent[-_MAX_RECENT:]
        state["updated_at"] = entry["at"]
        _save_state(state)

    logger.info(
        "desearch spend recorded cost_usd=%s usage_count=%s service=%s path=%s",
        billing.get("cost_usd"),
        billing.get("usage_count"),
        service,
        entry["path"][:80],
    )
    return billing


def get_spend_summary(*, recent_limit: int = 20) -> Dict[str, Any]:
    """Totals + recent billable calls for ops UI / API."""
    with _lock:
        state = _load_state()
    recent = list(state.get("recent") or [])
    limit = max(1, min(recent_limit, _MAX_RECENT))
    return {
        "total_usd": round(float(state.get("total_usd") or 0.0), 6),
        "total_items": int(state.get("total_items") or 0),
        "calls": int(state.get("calls") or 0),
        "billable_calls": int(state.get("billable_calls") or 0),
        "by_service": dict(state.get("by_service") or {}),
        "updated_at": state.get("updated_at"),
        "recent": recent[-limit:],
        "state_path": _state_path(),
    }
