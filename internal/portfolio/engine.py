"""§17.F3 — council paper portfolio from resolved predictions (no fake fills).

Follows each gradeable resolved council pick: long if direction=up, short if down.
P&L is alpha % vs holding TAO (benchmark always 0). Uses §16 direction grading.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from internal.council.grading import direction_correct, prediction_direction

_SKIP_OUTCOMES = frozenset({"duplicate", "expired", "ungradeable"})


def _gradeable_resolved(rows: List[Any]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        if row.get("outcome") in _SKIP_OUTCOMES:
            continue
        if row.get("actual_pct") is None:
            continue
        out.append(row)
    return out


def _position_from_resolved(row: Dict[str, Any]) -> Dict[str, Any]:
    actual = float(row["actual_pct"])
    direction = prediction_direction(row)
    # Follow the pick: up → long alpha; down → short alpha. Hold-TAO benchmark = 0.
    pnl_pct = actual if direction == "up" else -actual
    hit = direction_correct(row, actual)
    return {
        "id": row.get("id"),
        "netuid": row.get("netuid"),
        "name": row.get("name"),
        "direction": direction,
        "predicted_pct": row.get("predicted_pct"),
        "actual_pct": actual,
        "pnl_pct": round(pnl_pct, 4),
        "hold_tao_pnl_pct": 0.0,
        "excess_vs_hold_tao_pct": round(pnl_pct, 4),
        "direction_hit": hit,
        "resolved_at": row.get("resolved_at"),
        "created_at": row.get("created_at"),
        "horizon_hours": row.get("horizon_hours"),
    }


def build_portfolio_status(
    predictions_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Derive portfolio status from predictions store. Empty if nothing gradeable."""
    if predictions_data is None:
        try:
            from internal.learning.predictions_store import load_predictions

            predictions_data = load_predictions()
        except Exception:
            predictions_data = {"predictions": [], "resolved": []}

    closed = [_position_from_resolved(r) for r in _gradeable_resolved(predictions_data.get("resolved") or [])]
    wins = [p for p in closed if p.get("direction_hit")]
    total = len(closed)
    total_pnl = round(sum(float(p["pnl_pct"]) for p in closed), 4) if closed else 0.0

    # Open = pending predictions only (real rows, not invented fills).
    open_positions: List[Dict[str, Any]] = []
    for row in predictions_data.get("predictions") or []:
        if not isinstance(row, dict):
            continue
        if row.get("status") == "resolved":
            continue
        open_positions.append(
            {
                "id": row.get("id"),
                "netuid": row.get("netuid"),
                "name": row.get("name"),
                "direction": prediction_direction(row),
                "predicted_pct": row.get("predicted_pct"),
                "created_at": row.get("created_at"),
                "resolve_at": row.get("resolve_at"),
            }
        )

    return {
        "status": "ok",
        "empty": total == 0 and not open_positions,
        "benchmark": "hold_tao",
        "summary": {
            "open_positions": len(open_positions),
            "total_closed": total,
            "win_count": len(wins),
            "loss_count": total - len(wins),
            "win_pct": round(len(wins) / total, 4) if total else 0.0,
            "total_pnl_pct": total_pnl,
            "hold_tao_pnl_pct": 0.0,
            "excess_vs_hold_tao_pct": total_pnl,
            "grading": "direction_only_s16",
        },
        "closed_positions": closed,
        "open_positions": open_positions,
    }
