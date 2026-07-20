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
) -> Dict[str, Any]:
    """Build UI-ready trust banner from live resolver stats."""
    correct = int(stats.get("correct", 0) or 0)
    wrong = int(stats.get("wrong", 0) or 0)
    graded = correct + wrong
    expired = int(stats.get("expired", 0) or 0)
    duplicate = int(stats.get("duplicate", 0) or 0)
    pending = int(stats.get("pending", 0) or 0)
    total = int(stats.get("total", 0) or 0)
    if total <= 0:
        total = graded + expired + duplicate + pending

    expired_rate = round(expired / total, 3) if total > 0 else 0.0
    accuracy = round(correct / graded, 3) if graded > 0 else None

    integrity_ok = graded >= min_graded and expired_rate < max_expired_rate
    watchdog_warn = bool((watchdog or {}).get("warning"))

    if graded < min_graded:
        message = f"Not enough graded picks yet ({graded}/{min_graded})"
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

    streak = None
    streak_whisper = None
    try:
        from internal.learning.streaks import compute_streaks

        streak = compute_streaks()
        streak_whisper = streak.get("whisper")
    except Exception:
        streak = None

    return {
        "ready": integrity_ok and not watchdog_warn,
        "headline": headline,
        "message": message,
        "graded": graded,
        "correct": correct,
        "wrong": wrong,
        "accuracy": accuracy,
        "expired": expired,
        "expired_rate": expired_rate,
        "duplicate": duplicate,
        "pending": pending,
        "total": total,
        "min_graded": min_graded,
        "max_expired_rate": max_expired_rate,
        "integrity_gate": {
            "graded_ok": graded >= min_graded,
            "expired_ok": expired_rate < max_expired_rate,
            "watchdog_ok": not watchdog_warn,
        },
        "watchdog": watchdog,
        "source": "/api/learning/stats",
        "note": "Accuracy is direction-only on graded token price outcomes — excludes expired/duplicate.",
        "streak": streak,
        "streak_whisper": streak_whisper,
    }
