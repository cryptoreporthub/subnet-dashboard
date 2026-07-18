"""
Paper portfolio persistence for the Oracle / Echo / Pulse judges.

Each judge keeps a ledger of open and closed paper positions. Positions are
sized by the judge's confidence at entry time and closed when the underlying
prediction resolves. Performance is tracked overall and split by hourly vs
daily horizon.

Each judge has a different risk profile:
  - Oracle: standard risk (truth-focused, 1.0x)
  - Echo: conservative risk (consensus-focused, 0.7x)
  - Pulse: aggressive risk (momentum-focused, 1.3x)
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

PORTFOLIOS_PATH = os.path.join("data", "judge_portfolios.json")

# Per-judge risk multipliers — each judge trades with different conviction sizing
_JUDGE_RISK_MULTIPLIER = {
    "oracle": 1.0,   # Standard risk — truth-focused, balanced sizing
    "echo": 0.7,     # Conservative — consensus-focused, smaller positions
    "pulse": 1.3,    # Aggressive — momentum-focused, larger positions
}

_DEFAULT_JUDGE = {
    "open_positions": [],
    "closed_positions": [],
    "summary": {
        "open_positions": 0,
        "total_closed": 0,
        "win_count": 0,
        "loss_count": 0,
        "win_pct": 0.0,
        "total_pnl_pct": 0.0,
        "hourly": {"total": 0, "wins": 0, "win_pct": 0.0, "pnl_pct": 0.0},
        "daily": {"total": 0, "wins": 0, "win_pct": 0.0, "pnl_pct": 0.0},
    },
}

def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

def _load() -> Dict[str, Any]:
    try:
        with open(PORTFOLIOS_PATH, "r") as f:
            return json.load(f)
    except Exception:
        return {}

def _save(data: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(PORTFOLIOS_PATH) or ".", exist_ok=True)
    tmp = PORTFOLIOS_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, PORTFOLIOS_PATH)

def _get_judge(data: Dict[str, Any], name: str) -> Dict[str, Any]:
    name = name.lower()
    if name not in data:
        data[name] = json.loads(json.dumps(_DEFAULT_JUDGE))
    return data[name]

def _compute_pnl(direction: str, predicted_pct: float, actual_pct: float, judge_name: str = "oracle") -> float:
    """P&L for a paper position: aligned move positive, opposite move negative.
    
    Scaled by the judge's risk multiplier so each judge has differentiated returns.
    """
    if direction == "down":
        base_pnl = -actual_pct
    else:
        base_pnl = actual_pct
    multiplier = _JUDGE_RISK_MULTIPLIER.get(judge_name.lower(), 1.0)
    return round(base_pnl * multiplier, 4)

def _bucket(horizon_hours: Optional[int]) -> str:
    if horizon_hours is None:
        return "daily"
    return "hourly" if horizon_hours < 24 else "daily"

def _recompute_summary(judge_data: Dict[str, Any]) -> None:
    closed = judge_data.get("closed_positions", [])
    wins = [p for p in closed if p.get("pnl_pct", 0) > 0]
    losses = [p for p in closed if p.get("pnl_pct", 0) <= 0]

    hourly_closed = [p for p in closed if p.get("bucket") == "hourly"]
    hourly_wins = [p for p in hourly_closed if p.get("pnl_pct", 0) > 0]
    daily_closed = [p for p in closed if p.get("bucket") == "daily"]
    daily_wins = [p for p in daily_closed if p.get("pnl_pct", 0) > 0]

    def _bucket_stats(positions: List[Dict[str, Any]]) -> Dict[str, Any]:
        total = len(positions)
        wins_count = len([p for p in positions if p.get("pnl_pct", 0) > 0])
        return {
            "total": total,
            "wins": wins_count,
            "win_pct": round(wins_count / total, 4) if total else 0.0,
            "pnl_pct": round(sum(p.get("pnl_pct", 0) for p in positions), 4),
        }

    total_closed = len(closed)
    judge_data["summary"] = {
        "open_positions": len(judge_data.get("open_positions", [])),
        "total_closed": total_closed,
        "win_count": len(wins),
        "loss_count": len(losses),
        "win_pct": round(len(wins) / total_closed, 4) if total_closed else 0.0,
        "total_pnl_pct": round(sum(p.get("pnl_pct", 0) for p in closed), 4),
        "hourly": _bucket_stats(hourly_closed),
        "daily": _bucket_stats(daily_closed),
    }

def open_position(
    judge_name: str,
    prediction: Dict[str, Any],
    size: float = 1.0,
) -> Dict[str, Any]:
    """Open a paper position for a judge when a prediction is created."""
    data = _load()
    judge = _get_judge(data, judge_name)
    name_lower = judge_name.lower()
    
    # Scale position size by judge's risk multiplier
    risk_mult = _JUDGE_RISK_MULTIPLIER.get(name_lower, 1.0)
    adjusted_size = round(float(size) * risk_mult, 4)

    horizon = prediction.get("horizon_hours")
    position = {
        "id": prediction.get("id"),
        "netuid": prediction.get("netuid"),
        "name": prediction.get("name"),
        "direction": prediction.get("direction", "up"),
        "predicted_pct": float(prediction.get("predicted_pct", 0) or 0),
        "reference_price": float(prediction.get("reference_price", 0) or 0),
        "size": adjusted_size,
        "risk_multiplier": risk_mult,
        "bucket": _bucket(horizon),
        "horizon_hours": horizon,
        "entered_at": _utcnow(),
    }
    judge.setdefault("open_positions", []).append(position)
    _recompute_summary(judge)
    _save(data)
    return position

def close_position(
    judge_name: str,
    prediction: Dict[str, Any],
    actual_pct: Optional[float] = None,
    outcome: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Close an open paper position and move it to the closed ledger."""
    data = _load()
    judge = _get_judge(data, judge_name)
    open_positions = judge.get("open_positions", [])
    pred_id = prediction.get("id")
    netuid = prediction.get("netuid")

    idx = next(
        (
            i
            for i, pos in enumerate(open_positions)
            if pos.get("id") == pred_id or (pos.get("netuid") == netuid and pred_id is None)
        ),
        None,
    )

    direction = prediction.get("direction", "up")
    predicted_pct = float(prediction.get("predicted_pct", 0) or 0)

    if actual_pct is None:
        ref = float(prediction.get("reference_price", 0) or 0)
        resolved_price = float(prediction.get("resolved_price", 0) or 0)
        if ref > 0 and resolved_price > 0:
            actual_pct = (resolved_price - ref) / ref * 100
        else:
            actual_pct = 0.0
    actual_pct = float(actual_pct or 0)

    if idx is not None:
        position = open_positions.pop(idx)
        direction = position.get("direction", direction)
        predicted_pct = position.get("predicted_pct", predicted_pct)
    else:
        position = {
            "id": pred_id,
            "netuid": netuid,
            "name": prediction.get("name"),
            "direction": direction,
            "predicted_pct": predicted_pct,
            "reference_price": float(prediction.get("reference_price", 0) or 0),
            "size": 1.0,
            "bucket": _bucket(prediction.get("horizon_hours")),
            "horizon_hours": prediction.get("horizon_hours"),
            "entered_at": prediction.get("created_at"),
        }

    pnl = _compute_pnl(direction, predicted_pct, actual_pct, judge_name)
    closed = {
        **position,
        "actual_pct": round(actual_pct, 4),
        "pnl_pct": round(pnl * position.get("size", 1.0), 4),
        "outcome": outcome or prediction.get("outcome", "unknown"),
        "closed_at": _utcnow(),
    }
    judge.setdefault("closed_positions", []).append(closed)
    _recompute_summary(judge)
    _save(data)
    return closed

def get_portfolio(judge_name: str) -> Dict[str, Any]:
    """Return the full portfolio state for a judge."""
    data = _load()
    judge = _get_judge(data, judge_name)
    _recompute_summary(judge)
    return judge

def all_portfolios() -> Dict[str, Any]:
    """Return every judge portfolio keyed by judge name (read-only)."""
    data = _load()
    for name in ("oracle", "echo", "pulse"):
        _recompute_summary(_get_judge(data, name))
    return data
