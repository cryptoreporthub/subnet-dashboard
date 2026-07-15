"""Reproducible Oracle / Echo / Pulse backtest over resolved predictions."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from internal.council.grading import direction_correct
from internal.judges import echo_judge, oracle_judge, pulse_judge
from internal.judges.portfolios import _compute_pnl
from internal.learning.predictions_store import load_predictions

JUDGES = ("oracle", "echo", "pulse")
_SKIP_OUTCOMES = frozenset({"duplicate", "expired", "ungradeable"})
_CALIBRATION_BINS = 10


def _gradeable_rows(resolved: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for row in resolved:
        if not isinstance(row, dict):
            continue
        if row.get("outcome") in _SKIP_OUTCOMES:
            continue
        if row.get("status") not in (None, "resolved"):
            continue
        if row.get("actual_pct") is None:
            continue
        rows.append(row)
    return rows


def _signal_impact_from_row(row: Dict[str, Any]) -> Dict[str, Any]:
    if isinstance(row.get("market_impact"), dict) and row["market_impact"].get("impacts"):
        return row["market_impact"]
    source = str(row.get("signal_source") or "neutral").upper()
    pred_pct = float(row.get("predicted_pct") or 0)
    direction = row.get("direction") or ("up" if pred_pct >= 0 else "down")
    mag = abs(pred_pct) or 1.0
    impacts: List[Dict[str, Any]] = []
    if source in ("HOT", "SELL ALERT", "BUY", "SELL"):
        impacts.append(
            {
                "direction": "bullish" if source in ("HOT", "BUY") else "bearish",
                "magnitude_pct": mag,
                "signal": source.lower().replace(" ", "_"),
            }
        )
    elif pred_pct != 0:
        impacts.append(
            {
                "direction": "bullish" if direction == "up" else "bearish",
                "magnitude_pct": mag,
                "signal": "predicted_move",
            }
        )
    net_dir = impacts[0]["direction"] if impacts else "neutral"
    return {
        "impacts": impacts,
        "net_direction": net_dir,
        "net_predicted_pct": pred_pct,
        "dominant": source if source in ("HOT", "SELL ALERT") else None,
    }


def _subnet_from_row(row: Dict[str, Any]) -> Dict[str, Any]:
    subnet = row.get("subnet_snapshot") if isinstance(row.get("subnet_snapshot"), dict) else {}
    return {
        "price_change_24h": subnet.get("price_change_24h", row.get("price_change_24h_at_creation")),
        "price": subnet.get("price", row.get("reference_price")),
        "apy": subnet.get("apy", row.get("apy_at_creation")),
        "emission": subnet.get("emission", row.get("emission_at_creation")),
        "volume": subnet.get("volume", row.get("volume_at_creation")),
        "social_mentions": subnet.get("social_mentions", row.get("social_mentions_at_creation")),
    }


def _expert_weights_from_row(row: Dict[str, Any]) -> Dict[str, float]:
    weights = row.get("weights_at_creation")
    if isinstance(weights, dict):
        inner = weights.get("council_weights") or weights.get("expert_weights")
        if isinstance(inner, dict):
            return {str(k): float(v) for k, v in inner.items() if v is not None}
    return {}


def evaluate_judges(row: Dict[str, Any]) -> Dict[str, Dict[str, float]]:
    pred = dict(row)
    signal_impact = _signal_impact_from_row(row)
    subnet = _subnet_from_row(row)
    expert_weights = _expert_weights_from_row(row)
    return {
        "oracle": oracle_judge.evaluate(pred, signal_impact=signal_impact, subnet=subnet),
        "echo": echo_judge.evaluate(pred, signal_impact=signal_impact, expert_weights=expert_weights),
        "pulse": pulse_judge.evaluate(pred, signal_impact=signal_impact, subnet=subnet),
    }


def _init_judge_stats() -> Dict[str, Any]:
    return {
        "wins": 0,
        "losses": 0,
        "total_pnl_pct": 0.0,
        "calibration": [{"bin": i, "count": 0, "hits": 0} for i in range(_CALIBRATION_BINS)],
        "recent": [],
    }


def _calibration_hit(row: Dict[str, Any], actual_pct: float) -> bool:
    return direction_correct(row, actual_pct)


def run_backtest(
    *,
    data: Optional[Dict[str, Any]] = None,
    limit: Optional[int] = None,
) -> Dict[str, Any]:
    """Replay resolved predictions; measure paper P&L and calibration per judge."""
    payload = data if data is not None else load_predictions()
    rows = _gradeable_rows(payload.get("resolved") or [])
    if limit is not None and limit > 0:
        rows = rows[-limit:]

    if not rows:
        return {
            "status": "empty",
            "message": "No gradeable resolved predictions for backtest replay.",
            "sample_size": 0,
            "council": {"wins": 0, "losses": 0, "win_rate": None},
            "judges": {name: {**_init_judge_stats(), "win_rate": None, "avg_pnl_pct": None} for name in JUDGES},
            "history": [],
        }

    judges = {name: _init_judge_stats() for name in JUDGES}
    council_wins = 0
    history: List[Dict[str, Any]] = []

    for row in rows:
        actual_pct = float(row["actual_pct"])
        council_hit = _calibration_hit(row, actual_pct)
        if council_hit:
            council_wins += 1

        scores = evaluate_judges(row)
        entry: Dict[str, Any] = {
            "id": row.get("id"),
            "netuid": row.get("netuid"),
            "name": row.get("name"),
            "direction": row.get("direction"),
            "predicted_pct": row.get("predicted_pct"),
            "actual_pct": actual_pct,
            "council_correct": council_hit,
            "signal_source": row.get("signal_source"),
            "judges": {},
        }

        for name in JUDGES:
            judge_scores = scores[name]
            pnl = _compute_pnl(
                str(row.get("direction") or "up"),
                float(row.get("predicted_pct") or 0),
                actual_pct,
                name,
            )
            win = pnl > 0
            stats = judges[name]
            if win:
                stats["wins"] += 1
            else:
                stats["losses"] += 1
            stats["total_pnl_pct"] = round(stats["total_pnl_pct"] + pnl, 4)

            score = float(judge_scores.get("score") or 0.5)
            bin_idx = min(_CALIBRATION_BINS - 1, max(0, int(score * _CALIBRATION_BINS)))
            stats["calibration"][bin_idx]["count"] += 1
            if council_hit:
                stats["calibration"][bin_idx]["hits"] += 1

            entry["judges"][name] = {
                "score": judge_scores.get("score"),
                "confidence": judge_scores.get("confidence"),
                "pnl_pct": pnl,
                "win": win,
            }

        history.append(entry)

    n = len(rows)
    council_block = {
        "wins": council_wins,
        "losses": n - council_wins,
        "win_rate": round(council_wins / n, 4),
    }
    judge_blocks: Dict[str, Any] = {}
    for name in JUDGES:
        stats = judges[name]
        total = stats["wins"] + stats["losses"]
        cal = []
        for bucket in stats["calibration"]:
            count = bucket["count"]
            cal.append(
                {
                    "bin": bucket["bin"],
                    "score_lo": round(bucket["bin"] / _CALIBRATION_BINS, 2),
                    "score_hi": round((bucket["bin"] + 1) / _CALIBRATION_BINS, 2),
                    "count": count,
                    "hit_rate": round(bucket["hits"] / count, 4) if count else None,
                }
            )
        judge_blocks[name] = {
            "wins": stats["wins"],
            "losses": stats["losses"],
            "win_rate": round(stats["wins"] / total, 4) if total else None,
            "avg_pnl_pct": round(stats["total_pnl_pct"] / total, 4) if total else None,
            "total_pnl_pct": stats["total_pnl_pct"],
            "calibration": cal,
        }

    return {
        "status": "success",
        "sample_size": n,
        "council": council_block,
        "judges": judge_blocks,
        "history": list(reversed(history[-24:])),
    }


def load_backtest_from_path(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError("backtest fixture must be a JSON object")
    return run_backtest(data=data)
