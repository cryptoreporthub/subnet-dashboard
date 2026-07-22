"""Pre-pump triad — inflow quiet-load, buy pressure, price coil (SubnetAIQ-style)."""

from __future__ import annotations

from typing import Any, Dict, Optional


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def buy_pressure_ok(signals: Dict[str, Any], *, buy_ratio_min: float = 0.55) -> bool:
    """Buy-side flow meets the lead gate."""
    return _f(signals.get("buy_ratio"), 0.5) >= float(buy_ratio_min)


def tao_inflow_quiet_load(signals: Dict[str, Any]) -> bool:
    """TAO buying in without a price run yet — flow before price."""
    buy_ratio = _f(signals.get("buy_ratio"), 0.5)
    vol = _f(signals.get("volume_intensity"))
    mom_1h = _f(signals.get("momentum_1h"))
    chg_24h = _f(signals.get("price_change_24h"))
    return (
        buy_ratio >= 0.52
        and vol >= 0.12
        and mom_1h < 0.012
        and chg_24h < 0.04
    )


def price_coil(signals: Dict[str, Any]) -> bool:
    """Price stabilizing after a recent drop — coil before expansion."""
    chg_24h = _f(signals.get("price_change_24h"))
    mom_1h = _f(signals.get("momentum_1h"))
    if chg_24h > -0.015:
        return False
    # Flattening: 1h move less negative than the 24h drawdown pace.
    pace_24h = chg_24h / 24.0
    return mom_1h > pace_24h or abs(mom_1h) < 0.006


def compute_pump_triad(
    signals: Dict[str, Any],
    *,
    buy_ratio_min: Optional[float] = None,
) -> Dict[str, Any]:
    """Return triad booleans + strength label for pump desk cards."""
    if buy_ratio_min is None:
        try:
            from internal.learning.pump_calibration import effective_lead_gates

            buy_ratio_min = float(effective_lead_gates()["buy_ratio_min"])
        except Exception:
            buy_ratio_min = 0.55

    inflow = tao_inflow_quiet_load(signals)
    pressure = buy_pressure_ok(signals, buy_ratio_min=buy_ratio_min)
    coil = price_coil(signals)
    lit = sum((inflow, pressure, coil))
    if lit >= 3:
        strength = "STRONG"
    elif lit >= 2:
        strength = "BUILDING"
    else:
        strength = "WATCH"

    return {
        "inflow_quiet_load": inflow,
        "buy_pressure": pressure,
        "price_coil": coil,
        "lit_count": lit,
        "strength": strength,
    }


def attach_triad_to_signals(signals: Dict[str, Any]) -> Dict[str, Any]:
    """Merge triad fields into a signal snapshot dict (for ledger + cards)."""
    out = dict(signals)
    triad = compute_pump_triad(out)
    out["triad"] = triad
    out["triad_inflow"] = triad["inflow_quiet_load"]
    out["triad_pressure"] = triad["buy_pressure"]
    out["triad_coil"] = triad["price_coil"]
    out["triad_strength"] = triad["strength"]
    return out
