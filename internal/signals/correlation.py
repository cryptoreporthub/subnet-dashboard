"""Composite alert correlation rules (Phase L slice 4)."""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from internal.signals.rules import ALERT_DEDUP_WINDOW_MINUTES, _within_minutes

PRICE_CRASH_PCT = float(os.environ.get("COMPOSITE_PRICE_CRASH_PCT", "15"))
PRICE_SURGE_PCT = float(os.environ.get("COMPOSITE_PRICE_SURGE_PCT", "10"))
CONSENSUS_MIN_CONFIDENCE = float(os.environ.get("COMPOSITE_CONSENSUS_CONF", "0.6"))
CORE_EXPERTS = ("quant", "hype", "dark_horse", "technical")


def evaluate_composites(
    signals: List[Dict[str, Any]],
    recent_alerts: Optional[List[Dict[str, Any]]] = None,
    signal_history_by_subnet: Optional[Dict[int, List[Dict[str, Any]]]] = None,
) -> List[Dict[str, Any]]:
    """Return composite alert payloads (not yet persisted)."""
    recent_alerts = recent_alerts or []
    signal_history_by_subnet = signal_history_by_subnet or {}
    composites: List[Dict[str, Any]] = []
    by_subnet: Dict[int, Dict[str, Any]] = {}
    for sig in signals:
        sid = sig.get("subnet_id")
        if sid is None:
            continue
        by_subnet[int(sid)] = sig

    active_types = {
        str(a.get("alert_type"))
        for a in recent_alerts
        if a.get("active", True)
    }

    for sid, primary in by_subnet.items():
        hot = primary.get("hot") or {}
        sell = primary.get("sell") or {}
        pct = _float(primary.get("price_change_24h"))
        signal_type = str(primary.get("signal_type") or "neutral")

        if signal_type == "sell" and pct <= -PRICE_CRASH_PCT:
            composites.append(
                _composite(
                    "sell_crash",
                    sid,
                    "critical",
                    f"SN{sid} sell signal with {pct:+.1f}% 24h move",
                    {"subnet_id": sid, "price_change_24h": pct, "signal": primary},
                )
            )

        if hot.get("active") and signal_type == "buy" and pct >= PRICE_SURGE_PCT:
            composites.append(
                _composite(
                    "hot_surge",
                    sid,
                    "warning",
                    f"SN{sid} HOT buy with +{pct:.1f}% 24h surge",
                    {"subnet_id": sid, "price_change_24h": pct, "signal": primary},
                )
            )

        buy_experts = _buy_consensus_experts(primary)
        if len(buy_experts) >= 2:
            composites.append(
                _composite(
                    "expert_consensus_buy",
                    sid,
                    "info",
                    f"SN{sid} multi-expert buy consensus ({', '.join(sorted(buy_experts))})",
                    {"subnet_id": sid, "experts": sorted(buy_experts)},
                )
            )

        history = signal_history_by_subnet.get(sid) or []
        if _signal_flipped_recently(history, window_minutes=ALERT_DEDUP_WINDOW_MINUTES):
            composites.append(
                _composite(
                    "signal_flip",
                    sid,
                    "warning",
                    f"SN{sid} signal flipped within {ALERT_DEDUP_WINDOW_MINUTES}m window",
                    {"subnet_id": sid, "signals": history[-2:]},
                )
            )

    if "weight_divergence" in active_types and "accuracy_drop" in active_types:
        composites.append(
            _composite(
                "system_stress",
                None,
                "critical",
                "Weight divergence and accuracy drop both active",
                {"active_alerts": sorted(active_types)},
            )
        )

    return composites


def _buy_consensus_experts(signal: Dict[str, Any]) -> set[str]:
    """Experts with buy-leaning contribution scores on the latest snapshot."""
    if str(signal.get("signal_type") or "") != "buy":
        return set()
    contribs = signal.get("expert_contributions") or {}
    return {
        name
        for name in CORE_EXPERTS
        if _float(contribs.get(name)) >= CONSENSUS_MIN_CONFIDENCE
    }


def _composite(
    rule_id: str,
    subnet_id: Optional[int],
    severity: str,
    message: str,
    details: Dict[str, Any],
) -> Dict[str, Any]:
    dedupe = f"composite_{rule_id}_{subnet_id}" if subnet_id is not None else f"composite_{rule_id}"
    return {
        "alert_type": f"composite_{rule_id}",
        "severity": severity,
        "message": message,
        "details": details,
        "subnet_id": subnet_id,
        "dedupe_key": dedupe,
        "active": True,
    }


def _float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _signal_flipped_recently(
    rows: List[Dict[str, Any]],
    *,
    window_minutes: int = ALERT_DEDUP_WINDOW_MINUTES,
) -> bool:
    if len(rows) < 2:
        return False
    ordered = sorted(rows, key=lambda r: str(r.get("timestamp") or ""))
    prev_row = ordered[-2]
    curr_row = ordered[-1]
    prev_type = prev_row.get("signal_type")
    curr_type = curr_row.get("signal_type")
    if prev_type == curr_type:
        return False
    flip_pairs = {("buy", "sell"), ("sell", "buy")}
    if (prev_type, curr_type) not in flip_pairs:
        return False
    prev_ts = str(prev_row.get("timestamp") or "")
    curr_ts = str(curr_row.get("timestamp") or "")
    return bool(prev_ts and curr_ts and _within_minutes(prev_ts, curr_ts, window_minutes))
