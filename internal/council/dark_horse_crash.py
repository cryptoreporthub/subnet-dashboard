"""Dark Horse crash-tail features — Martin & Shi (2024) inspired proxies.

We do not have equity options on subnets; we approximate crash-probability
semantics with downside drawdown, tail volatility, and recovery setup signals.
"""

from __future__ import annotations

from typing import Any, Dict

FORMULA_VERSION = "1.2.0"


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


def crash_tail_features(sn: Dict[str, Any]) -> Dict[str, float]:
    """Downside-tail proxy features from price change history."""
    chg_24 = float(sn.get("price_change_24h") or 0)
    chg_7d = float(sn.get("price_change_7d") or 0)
    chg_30 = float(sn.get("price_change_30d") or chg_7d or 0)

    drawdown = min(chg_24, chg_7d, chg_30, 0.0)
    crash_stress = _clamp(abs(drawdown) / 20.0)
    tail_risk = _clamp((abs(chg_24) + abs(chg_7d) * 0.5) / 25.0)

    recovery_signal = 0.5
    if chg_7d < -5.0 and chg_24 > chg_7d * 0.3:
        recovery_signal = _clamp(0.55 + (chg_24 - chg_7d) / 40.0)

    crash_opportunity = _clamp(
        0.45 * crash_stress + 0.35 * max(0.0, recovery_signal - 0.5) * 2.0 + 0.20 * (1.0 - tail_risk)
    )

    return {
        "drawdown_pct": round(drawdown, 4),
        "crash_stress": round(crash_stress, 4),
        "tail_risk": round(tail_risk, 4),
        "recovery_signal": round(recovery_signal, 4),
        "crash_opportunity": round(crash_opportunity, 4),
    }


def dark_horse_crash_score(sn: Dict[str, Any]) -> float:
    """Single 0–1 crash-opportunity score for blending into Dark Horse."""
    return crash_tail_features(sn)["crash_opportunity"]
