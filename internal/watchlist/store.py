"""§17.F1 — pinned subnet watchlist (server JSON, not committed)."""

from __future__ import annotations

import json
import os
import secrets
from pathlib import Path
from typing import Any, Dict, List, Optional

WATCHLIST_PATH = os.environ.get("WATCHLIST_PATH", "data/watchlist.json")


def _default() -> Dict[str, Any]:
    return {"netuids": [], "thresholds": {}, "alerts": {}, "updated_at": None}


def _read_document(path: str) -> Dict[str, Any]:
    try:
        raw = Path(path).read_text(encoding="utf-8")
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def _normalize(data: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(data, dict):
        return _default()
    netuids = data.get("netuids") or []
    if not isinstance(netuids, list):
        netuids = []
    cleaned: List[int] = []
    seen = set()
    for n in netuids:
        try:
            i = int(n)
        except (TypeError, ValueError):
            continue
        if i <= 0 or i in seen:
            continue
        seen.add(i)
        cleaned.append(i)
    thresholds = data.get("thresholds") or {}
    if not isinstance(thresholds, dict):
        thresholds = {}
    cleaned_thresholds: Dict[str, float] = {}
    for key, value in thresholds.items():
        try:
            cleaned_thresholds[str(int(key))] = float(value)
        except (TypeError, ValueError):
            continue
    alerts = data.get("alerts") or {}
    if not isinstance(alerts, dict):
        alerts = {}
    cleaned_alerts: Dict[str, Any] = {}
    for key, value in alerts.items():
        if isinstance(value, dict):
            cleaned_alerts[str(key)] = {k: bool(v) for k, v in value.items() if k in ("enabled",)}
    return {
        "netuids": cleaned,
        "thresholds": cleaned_thresholds,
        "alerts": cleaned_alerts,
        "updated_at": data.get("updated_at"),
    }


def load_watchlist(path: Optional[str] = None, *, owner: Optional[str] = None) -> Dict[str, Any]:
    path = path or WATCHLIST_PATH
    data = _read_document(path)
    if owner is not None:
        profiles = data.get("profiles") or {}
        return _normalize(profiles.get(str(owner)) if isinstance(profiles, dict) else {})
    return _normalize(data)


def save_watchlist(
    netuids: List[Any],
    path: Optional[str] = None,
    thresholds: Optional[Dict[str, Any]] = None,
    alerts: Optional[Dict[str, Any]] = None,
    *,
    owner: Optional[str] = None,
) -> Dict[str, Any]:
    from datetime import datetime, timezone

    path = path or WATCHLIST_PATH
    cleaned: List[int] = []
    seen = set()
    for n in netuids or []:
        try:
            i = int(n)
        except (TypeError, ValueError):
            continue
        if i <= 0 or i in seen:
            continue
        seen.add(i)
        cleaned.append(i)

    payload: Dict[str, Any] = {
        "netuids": cleaned,
        "thresholds": {},
        "alerts": {},
        "updated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    for key, value in (thresholds or {}).items():
        try:
            netuid = str(int(key))
            payload["thresholds"][netuid] = float(value)
        except (TypeError, ValueError):
            continue
    for key, value in (alerts or {}).items():
        if isinstance(value, dict):
            payload["alerts"][str(key)] = {k: bool(v) for k, v in value.items() if k in ("enabled",)}
    dest = Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    document = payload
    if owner is not None:
        existing = _read_document(path)
        profiles = existing.get("profiles") or {}
        if not isinstance(profiles, dict):
            profiles = {}
        profiles[str(owner)] = payload
        document = {
            "version": 2,
            "profiles": profiles,
            "updated_at": payload["updated_at"],
        }
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    tmp.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    tmp.replace(dest)
    return payload


def create_link_code(owner: str, path: Optional[str] = None) -> str:
    """Create a short-lived-ish one-time browser↔Telegram link code."""
    path = path or WATCHLIST_PATH
    data = _read_document(path)
    codes = data.get("link_codes") or {}
    if not isinstance(codes, dict):
        codes = {}
    code = secrets.token_urlsafe(8).replace("-", "").replace("_", "")[:10].upper()
    codes[code] = str(owner)
    data["link_codes"] = codes
    _write_document(path, data)
    return code


def claim_link_code(code: str, telegram_owner: str, path: Optional[str] = None) -> Optional[str]:
    path = path or WATCHLIST_PATH
    data = _read_document(path)
    codes = data.get("link_codes") or {}
    if not isinstance(codes, dict):
        return None
    browser_owner = codes.pop(str(code or "").strip().upper(), None)
    if not browser_owner:
        return None
    links = data.get("telegram_links") or {}
    if not isinstance(links, dict):
        links = {}
    links[str(telegram_owner)] = str(browser_owner)
    data["link_codes"] = codes
    data["telegram_links"] = links
    _write_document(path, data)
    return str(browser_owner)


def linked_owner(telegram_owner: str, path: Optional[str] = None) -> Optional[str]:
    data = _read_document(path or WATCHLIST_PATH)
    links = data.get("telegram_links") or {}
    if not isinstance(links, dict):
        return None
    owner = links.get(str(telegram_owner))
    return str(owner) if owner else None


def _write_document(path: str, data: Dict[str, Any]) -> None:
    dest = Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    tmp.replace(dest)
