"""§17.F2 — optional external delivery for conviction alerts (flag-gated)."""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_ENABLED = frozenset({"1", "true", "on", "yes"})


def delivery_mode() -> str:
    """off | dry_run | webhook | telegram — default off (CI-safe)."""
    raw = (os.environ.get("CONVICTION_ALERT_DELIVERY") or "off").strip().lower()
    if raw in {"off", "0", "false", "no", ""}:
        return "off"
    if raw in {"dry_run", "dry-run", "dry"}:
        return "dry_run"
    if raw in {"webhook", "http", "https"}:
        return "webhook"
    if raw in {"telegram", "tg"}:
        return "telegram"
    return "off"


def _watchlist_netuids() -> Optional[List[int]]:
    """If watchlist has pins, restrict delivery to those netuids; else None = all."""
    try:
        from internal.watchlist.store import load_watchlist

        pins = load_watchlist().get("netuids") or []
        if pins:
            return [int(n) for n in pins]
    except Exception:
        pass
    return None


def _filter_alerts(alerts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    pins = _watchlist_netuids()
    if pins is None:
        return list(alerts)
    pinset = set(pins)
    out = []
    for a in alerts:
        sid = a.get("subnet_id")
        if sid is None:
            details = a.get("details") if isinstance(a.get("details"), dict) else {}
            sid = details.get("netuid")
        try:
            if sid is not None and int(sid) in pinset:
                out.append(a)
        except (TypeError, ValueError):
            continue
    return out


def _post_json(url: str, payload: Dict[str, Any], timeout: float = 8.0) -> Dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", "User-Agent": "subnet-dashboard-alerts"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return {"ok": True, "status": getattr(resp, "status", 200)}
    except urllib.error.HTTPError as exc:
        return {"ok": False, "status": exc.code, "error": str(exc)}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _telegram_payload(alert: Dict[str, Any]) -> Dict[str, Any]:
    text = str(alert.get("message") or "conviction alert")
    return {"text": text, "disable_web_page_preview": True}


def deliver_alerts(alerts: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Send or dry-run delivery. Never raises; CI stays green with mode=off."""
    mode = delivery_mode()
    filtered = _filter_alerts(alerts)
    result: Dict[str, Any] = {
        "mode": mode,
        "attempted": 0,
        "delivered": 0,
        "skipped_watchlist": max(0, len(alerts) - len(filtered)),
        "dry_run": [],
        "errors": [],
    }
    if mode == "off":
        result["reason"] = "delivery_off"
        return result
    if not filtered:
        result["reason"] = "nothing_to_deliver"
        return result

    webhook = os.environ.get("CONVICTION_ALERT_WEBHOOK_URL", "").strip()
    tg_token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    tg_chat = os.environ.get("TELEGRAM_ALERT_CHAT_ID", "").strip()

    for alert in filtered:
        result["attempted"] += 1
        if mode == "dry_run":
            result["dry_run"].append(
                {
                    "dedupe_key": alert.get("dedupe_key"),
                    "message": alert.get("message"),
                    "subnet_id": alert.get("subnet_id"),
                }
            )
            result["delivered"] += 1
            continue

        if mode == "webhook":
            if not webhook:
                result["errors"].append("CONVICTION_ALERT_WEBHOOK_URL unset")
                break
            resp = _post_json(webhook, {"alert": alert})
            if resp.get("ok"):
                result["delivered"] += 1
            else:
                result["errors"].append(resp)
            continue

        if mode == "telegram":
            if not tg_token or not tg_chat:
                result["errors"].append("TELEGRAM_BOT_TOKEN or TELEGRAM_ALERT_CHAT_ID unset")
                break
            url = f"https://api.telegram.org/bot{tg_token}/sendMessage"
            payload = {**_telegram_payload(alert), "chat_id": tg_chat}
            resp = _post_json(url, payload)
            if resp.get("ok"):
                result["delivered"] += 1
            else:
                result["errors"].append(resp)
            continue

    return result
