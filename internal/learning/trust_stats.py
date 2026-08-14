"""Honest trust-banner stats for Living Brain UI (RF-2).

Never hardcode target accuracy. Read resolver stats only; honest-empty when thin
or when expired backlog is too high (RF-3 gate).
"""

from __future__ import annotations

from typing import Any, Dict, Optional

MIN_GRADED_SAMPLE = 30
MAX_EXPIRED_RATE = 0.10
_SKIP = frozenset({"duplicate", "expired", "ungradeable"})


def build_trust_banner(
    stats: Dict[str, Any],
    *,
    watchdog: Optional[Dict[str, Any]] = None,
    min_graded: int = MIN_GRADED_SAMPLE,
    max_expired_rate: float = MAX_EXPIRED_RATE,
    ledger_context: Optional[Dict[str, Any]] = None,
    predictions_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build UI-ready trust banner from live resolver stats."""
    correct = int(stats.get("correct", 0) or 0)
    wrong = int(stats.get("wrong", 0) or 0)
    graded = correct + wrong
    expired = int(stats.get("expired", 0) or 0)
    expired_genuine = int(stats.get("expired_genuine", 0) or 0)
    ungradeable = int(stats.get("ungradeable", 0) or 0)
    price_data_unavailable = int(stats.get("price_data_unavailable", 0) or 0)
    duplicate = int(stats.get("duplicate", 0) or 0)
    pending = int(stats.get("pending", 0) or 0)
    council_pending = int(stats.get("council_pending", pending) or 0)
    pump_pending = int(stats.get("pump_pending", 0) or 0)
    total_pending = int(stats.get("total_pending", council_pending + pump_pending) or 0)
    total = int(stats.get("total", 0) or 0)
    if total <= 0:
        total = graded + expired + duplicate + pending

    # Expired-rate is about the RESOLVED flow, not the raw total: pending rows
    # are still in flight and duplicates are a labeling artifact. Keep a legacy
    # total-based rate for back-compat, but gate on the honest resolved rate.
    resolved_total = graded + expired + duplicate
    expired_rate = round(expired / resolved_total, 3) if resolved_total > 0 else 0.0
    expired_total_rate = round(expired / total, 3) if total > 0 else 0.0
    accuracy = round(correct / graded, 3) if graded > 0 else None

    integrity_ok = graded >= min_graded and expired_rate < max_expired_rate
    watchdog_warn = bool((watchdog or {}).get("warning"))

    if graded < min_graded:
        shadow_graded = int(stats.get("shadow_graded", 0) or 0)
        if shadow_graded > 0:
            message = (
                f"Published council sample {graded}/{min_graded} — "
                f"{shadow_graded} HOLD shadow grades excluded from trust"
            )
        else:
            message = f"Not enough graded picks yet ({graded}/{min_graded})"
            if expired > 0:
                message += (
                    f" \u00b7 backlog {expired} expired ({round(expired_rate * 100)}% of resolved) "
                    f"- resolved-flow denominator; {price_data_unavailable} missing-price retirements"
                )
        headline = None
    elif expired_rate >= max_expired_rate:
        message = (
            f"Resolver backlog high — {round(expired_rate * 100)}% expired "
            f"(need <{round(max_expired_rate * 100)}% before trust surfaces)"
        )
        headline = None
    else:
        pct = round((accuracy or 0) * 100)
        message = None
        headline = f"Last {graded} graded: {pct}% directionally right"

    if watchdog_warn:
        gate_reason = (watchdog or {}).get("reason") or "resolver_watchdog"
    elif graded < min_graded:
        gate_reason = "insufficient_graded_sample"
    elif expired_rate >= max_expired_rate:
        gate_reason = "expired_backlog"
    else:
        gate_reason = "qualified"

    streak = None
    streak_whisper = None
    try:
        from internal.learning.streaks import compute_streaks

        streak = compute_streaks(predictions_data)
        streak_whisper = streak.get("whisper")
    except Exception:
        streak = None

    ledger_graded_30d = None
    ledger_hit_rate_30d = None
    ledger_published_graded_30d = None
    ledger_published_hit_rate_30d = None
    ledger_note = None
    if isinstance(ledger_context, dict) and ledger_context.get("data_available"):
        full_ledger = ledger_context.get("full_ledger") or {}
        published = ledger_context.get("published_only") or {}
        try:
            ledger_graded_30d = int(full_ledger.get("graded_30d") or ledger_context.get("graded_30d") or 0)
        except (TypeError, ValueError):
            ledger_graded_30d = None
        raw_rate = full_ledger.get("hit_rate_30d")
        if raw_rate is None:
            raw_rate = ledger_context.get("hit_rate_30d")
        if raw_rate is not None:
            try:
                ledger_hit_rate_30d = round(float(raw_rate), 4)
            except (TypeError, ValueError):
                ledger_hit_rate_30d = None
        if published.get("data_available"):
            try:
                ledger_published_graded_30d = int(published.get("graded_30d") or 0)
            except (TypeError, ValueError):
                ledger_published_graded_30d = None
            pub_rate = published.get("hit_rate_30d")
            if pub_rate is not None:
                try:
                    ledger_published_hit_rate_30d = round(float(pub_rate), 4)
                except (TypeError, ValueError):
                    ledger_published_hit_rate_30d = None
        ledger_note = (
            "Full resolved ledger (30d); panel shows published-only when available. "
            "Trust gate uses published LONG picks only (excludes HOLD shadows and pump-desk claims)."
        )

    return {
        "ready": integrity_ok and not watchdog_warn,
        "headline": headline,
        "message": message,
        "graded": graded,
        "correct": correct,
        "wrong": wrong,
        "accuracy": accuracy,
        "expired": expired,
        "expired_genuine": expired_genuine,
        "ungradeable": ungradeable,
        "price_data_unavailable": price_data_unavailable,
        "expired_rate": expired_rate,
        "expired_total_rate": expired_total_rate,
        "expired_note": (
            f"{expired} rows retired as expired, {ungradeable} ungradeable; "
            f"{price_data_unavailable} have an explicit missing-price reason. "
            f"expired/(graded+expired+duplicate) = {expired_rate}; gate activates at {min_graded} graded."
        ) if expired else None,
        "duplicate": duplicate,
        "pending": pending,
        "council_pending": council_pending,
        "pump_pending": pump_pending,
        "total_pending": total_pending,
        "total": total,
        "min_graded": min_graded,
        "max_expired_rate": max_expired_rate,
        "integrity_gate": {
            "graded_ok": graded >= min_graded,
            "expired_ok": (expired_rate < max_expired_rate) if graded >= min_graded else None,
            "watchdog_ok": not watchdog_warn,
        },
        "sample": {
            "graded": graded,
            "correct": correct,
            "wrong": wrong,
            "pending": pending,
            "expired": expired,
            "duplicate": duplicate,
            "total": total,
            "minimum": min_graded,
        },
        "gate_reason": gate_reason,
        "watchdog": watchdog,
        "source": "/api/learning/stats",
        "note": (
            "Accuracy is direction-only on graded token price outcomes — "
            "excludes expired/duplicate/HOLD-shadow/pump-desk claims."
        ),
        "shadow_graded": int(stats.get("shadow_graded", 0) or 0),
        "streak": streak,
        "streak_whisper": streak_whisper,
        "ledger_graded_30d": ledger_graded_30d,
        "ledger_hit_rate_30d": ledger_hit_rate_30d,
        "ledger_published_graded_30d": ledger_published_graded_30d,
        "ledger_published_hit_rate_30d": ledger_published_hit_rate_30d,
        "ledger_note": ledger_note,
    }
