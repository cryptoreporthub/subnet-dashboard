"""Signal rules engine — SELL > HOT precedence and deduplication (Phase L slice 4).

Design: cursor-agents-communication/phase-l-slice4-rules-design.md
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple

SELL_LABEL = "SELL ALERT"
HOT_LABEL = "HOT"

ALLOWED_SEVERITIES = frozenset({"info", "warning", "critical"})
ALLOWED_THRESHOLD_OPS = frozenset({"gt", "lt", "gte", "lte", "eq"})
ALERT_DEDUP_WINDOW_MINUTES = int(os.environ.get("ALERT_DEDUP_WINDOW_MINUTES", "5"))
ALERT_MAX_PER_SUBNET_HOUR = int(os.environ.get("ALERT_MAX_PER_SUBNET_HOUR", "10"))


def _parse_ts(value: str) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


def _within_minutes(ts_a: str, ts_b: str, minutes: int) -> bool:
    a = _parse_ts(ts_a)
    b = _parse_ts(ts_b)
    if not a or not b:
        return False
    return abs((b - a).total_seconds()) <= minutes * 60


def apply_hot_sell_precedence(
    hot: Dict[str, Any],
    sell: Dict[str, Any],
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Return copies with SELL taking precedence over HOT."""
    hot_out = dict(hot or {})
    sell_out = dict(sell or {})
    if sell_out.get("active"):
        hot_out["active"] = False
        hot_out["suppressed_by"] = SELL_LABEL
    return hot_out, sell_out


def derive_signal_type(
    total_score: float,
    hot: Dict[str, Any],
    sell: Dict[str, Any],
) -> str:
    """Map council score + hot/sell flags to buy|sell|neutral."""
    _, sell_adj = apply_hot_sell_precedence(hot, sell)
    hot_adj, _ = apply_hot_sell_precedence(hot, sell)
    if sell_adj.get("active"):
        return "sell"
    if hot_adj.get("active") and total_score >= 50:
        return "buy"
    if total_score >= 60:
        return "buy"
    if total_score <= 40:
        return "sell"
    return "neutral"


def dominant_label(hot: Dict[str, Any], sell: Dict[str, Any]) -> Optional[str]:
    """UI-facing dominant tag: SELL ALERT > HOT > None."""
    if sell.get("active"):
        return SELL_LABEL
    if hot.get("active"):
        return HOT_LABEL
    return None


def signals_unchanged(prev: Dict[str, Any], nxt: Dict[str, Any]) -> bool:
    """True when persisted signal row would be a duplicate."""
    keys = ("signal_type", "source_expert", "confidence")
    return all(prev.get(k) == nxt.get(k) for k in keys)


def signal_dedupe_key(signal: Dict[str, Any]) -> str:
    sid = signal.get("subnet_id")
    return f"signal_{sid}_{signal.get('signal_type')}_{signal.get('source_expert')}"


def alert_dedupe_key(alert: Dict[str, Any]) -> str:
    explicit = alert.get("dedupe_key")
    if explicit:
        return str(explicit)
    alert_type = alert.get("alert_type") or "unknown"
    sid = alert.get("subnet_id")
    if sid is not None:
        return f"{alert_type}_{sid}"
    return str(alert_type)


def should_skip_alert(
    existing: Dict[str, Any],
    candidate: Dict[str, Any],
) -> bool:
    """Skip when same dedupe key + type is active, or same subnet+type within window."""
    if alert_dedupe_key(existing) == alert_dedupe_key(candidate) and existing.get(
        "alert_type"
    ) == candidate.get("alert_type"):
        if existing.get("active"):
            return True
        cand_ts = str(candidate.get("timestamp") or "")
        exist_ts = str(existing.get("timestamp") or "")
        if cand_ts and exist_ts and _within_minutes(
            exist_ts, cand_ts, ALERT_DEDUP_WINDOW_MINUTES
        ):
            return True

    sid = candidate.get("subnet_id")
    if sid is not None and existing.get("subnet_id") == sid:
        if existing.get("alert_type") == candidate.get("alert_type"):
            cand_ts = str(candidate.get("timestamp") or "")
            exist_ts = str(existing.get("timestamp") or "")
            if cand_ts and exist_ts and _within_minutes(
                exist_ts, cand_ts, ALERT_DEDUP_WINDOW_MINUTES
            ):
                return True
    return False


def subnet_hourly_cap_reached(
    alerts: list[Dict[str, Any]],
    subnet_id: int,
    *,
    max_per_hour: int = ALERT_MAX_PER_SUBNET_HOUR,
) -> bool:
    """True when subnet_id already has max_per_hour alerts in the last hour."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
    count = 0
    for row in alerts:
        if row.get("subnet_id") != subnet_id:
            continue
        ts = _parse_ts(str(row.get("timestamp") or ""))
        if ts and ts >= cutoff:
            count += 1
            if count >= max_per_hour:
                return True
    return False


def validate_alert_payload(payload: Dict[str, Any]) -> Optional[str]:
    """Return error message or None if valid."""
    alert_type = str(payload.get("alert_type") or "").strip()
    message = str(payload.get("message") or "").strip()
    if not alert_type:
        return "alert_type is required"
    if not message:
        return "message is required"
    severity = str(payload.get("severity") or "info").strip().lower()
    if severity not in ALLOWED_SEVERITIES:
        return f"severity must be one of: {', '.join(sorted(ALLOWED_SEVERITIES))}"

    subnet_id = payload.get("subnet_id")
    if subnet_id is not None and not isinstance(subnet_id, int):
        return "subnet_id (netuid) must be an integer"

    threshold_type = payload.get("threshold_type")
    threshold_value = payload.get("threshold_value")
    threshold_operator = payload.get("threshold_operator")
    if threshold_type is not None or threshold_value is not None:
        if not str(threshold_type or "").strip():
            return "threshold_type is required when configuring a threshold alert"
        if threshold_value is None:
            return "threshold_value is required when configuring a threshold alert"
        try:
            float(threshold_value)
        except (TypeError, ValueError):
            return "threshold_value must be numeric"
        op = str(threshold_operator or "gte").strip().lower()
        if op not in ALLOWED_THRESHOLD_OPS:
            return f"threshold_operator must be one of: {', '.join(sorted(ALLOWED_THRESHOLD_OPS))}"
    return None
