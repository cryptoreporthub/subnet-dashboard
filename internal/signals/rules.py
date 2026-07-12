"""Signal rules engine — SELL > HOT precedence and deduplication (Phase L slice 4).

Design notes (Grok pass → Composer implementation):
- SELL ALERT always suppresses HOT when both flags are active.
- Signal persistence dedupes unchanged (type, expert, confidence) per subnet.
- Alert dedupes on dedupe_key + alert_type while prior row is still active.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

SELL_LABEL = "SELL ALERT"
HOT_LABEL = "HOT"

ALLOWED_SEVERITIES = frozenset({"info", "warning", "critical"})


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
    """Skip when same dedupe key + type is already active."""
    if not existing.get("active"):
        return False
    return (
        alert_dedupe_key(existing) == alert_dedupe_key(candidate)
        and existing.get("alert_type") == candidate.get("alert_type")
    )


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
    return None
