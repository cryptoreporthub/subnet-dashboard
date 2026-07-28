"""Council health score for Ditto Council Health Monitor (artifact producer).

Matches manual Ditto run shape: score ≈ round(accuracy * 200) + integrity bonus.
Escalation: WATCH when score < 70 or directional accuracy < 35%.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

WATCH_SCORE_FLOOR = 70
WATCH_ACCURACY_FLOOR = 0.35
ALERT_ACCURACY_FLOOR = 0.25


def compute_council_health(
    resolver_stats: Dict[str, Any],
    trust_banner: Dict[str, Any],
    loop_health: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    correct = int(resolver_stats.get("correct", 0) or 0)
    wrong = int(resolver_stats.get("wrong", 0) or 0)
    graded = correct + wrong
    accuracy = float(resolver_stats.get("accuracy", 0) or 0) if graded > 0 else 0.0

    gates = trust_banner.get("integrity_gate") or {}
    integrity_ok = bool(
        gates.get("graded_ok") and gates.get("expired_ok") and gates.get("watchdog_ok")
    )
    score = min(100, max(0, round(accuracy * 200) + (1 if integrity_ok else 0)))

    reasons: List[str] = []
    escalation = "OK"
    if score < WATCH_SCORE_FLOOR:
        reasons.append(f"Health score {score} < {WATCH_SCORE_FLOOR} (WATCH threshold)")
    if graded > 0 and accuracy < WATCH_ACCURACY_FLOOR:
        reasons.append(
            f"Directional accuracy {round(accuracy * 100)}% < "
            f"{round(WATCH_ACCURACY_FLOOR * 100)}%"
        )
    if reasons:
        escalation = "WATCH"

    loop_status = str((loop_health or {}).get("status") or "").lower()
    if loop_status in ("stalled", "error"):
        escalation = "ALERT"
        reasons.append(f"learning_loop status={loop_status}")
    elif graded > 0 and accuracy < ALERT_ACCURACY_FLOOR:
        escalation = "ALERT"
        reasons.append(f"Directional accuracy {round(accuracy * 100)}% < 25%")

    return {
        "health_score": score,
        "escalation": escalation,
        "escalation_reasons": reasons,
        "directional_accuracy": round(accuracy, 3) if graded > 0 else None,
        "graded": graded,
        "correct": correct,
        "wrong": wrong,
        "integrity_gates": gates,
        "integrity_ok": integrity_ok,
    }
