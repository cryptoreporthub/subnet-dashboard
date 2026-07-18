"""Reproducible Oracle / Echo / Pulse backtest over resolved predictions."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from internal.analytics.backtest_methodology import build_methodology_payload
from internal.council.grading import direction_correct
from internal.judges import echo_judge, oracle_judge, pulse_judge
from internal.judges.portfolios import _compute_pnl
from internal.learning.predictions_store import load_predictions

JUDGES = ("oracle", "echo", "pulse")
_SKIP_OUTCOMES = frozenset({"duplicate", "expired", "ungradeable"})
_CALIBRATION_BINS = 10
_RISK_COVERAGE_THRESHOLDS = (0.45, 0.5, 0.55, 0.6, 0.65, 0.7, 0.75, 0.8, 0.85, 0.9)
_JUDGE_THRESHOLDS: Dict[str, float] = {
    "oracle": 0.55,
    "echo": 0.5,
    "pulse": 0.55,
}


def _judge_threshold(judge: str) -> float:
    return _JUDGE_THRESHOLDS.get(judge, 0.55)


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
        sig = str(row.get("signal_source") or "predicted_move").lower().replace(" ", "_")
        impacts.append(
            {
                "direction": "bullish" if direction == "up" else "bearish",
                "magnitude_pct": mag,
                "signal": sig,
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
        "price_change_7d": subnet.get("price_change_7d", row.get("price_change_7d_at_creation")),
        "price": subnet.get("price", row.get("reference_price")),
        "apy": subnet.get("apy", row.get("apy_at_creation")),
        "staking_yield_apy": subnet.get("staking_yield_apy"),
        "emission": subnet.get("emission", row.get("emission_at_creation")),
        "volume": subnet.get("volume", row.get("volume_at_creation")),
        "social_mentions": subnet.get("social_mentions", row.get("social_mentions_at_creation")),
        "yield_trap": subnet.get("yield_trap"),
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


def _filtered_judge_win_rate(
    history: List[Dict[str, Any]],
    judge: str,
    *,
    min_score: Optional[float] = None,
) -> Dict[str, Any]:
    """Hit-rate on picks the judge endorses (score at or above threshold)."""
    min_score = _judge_threshold(judge) if min_score is None else min_score
    picks = [
        h
        for h in history
        if isinstance(h.get("judges"), dict)
        and isinstance(h["judges"].get(judge), dict)
        and float(h["judges"][judge].get("score") or 0) >= min_score
    ]
    if not picks:
        return {
            "n": 0,
            "win_rate": None,
            "min_score": min_score,
            "coverage": None,
            "coverage_pct": None,
        }
    wins = sum(1 for h in picks if h.get("council_correct"))
    return {
        "n": len(picks),
        "win_rate": round(wins / len(picks), 4),
        "min_score": min_score,
        "coverage": None,
        "coverage_pct": None,
    }


def _with_coverage(filtered: Dict[str, Any], sample_size: int) -> Dict[str, Any]:
    out = dict(filtered)
    if sample_size > 0 and out.get("n") is not None:
        out["coverage"] = round(float(out["n"]) / sample_size, 4)
        out["coverage_pct"] = round(100.0 * float(out["n"]) / sample_size, 1)
    return out


def _risk_coverage_curve(
    history: List[Dict[str, Any]],
    judge: str,
    *,
    sample_size: int,
) -> List[Dict[str, Any]]:
    """Selective risk vs coverage at score thresholds (El-Yaniv & Wiener 2010)."""
    if sample_size <= 0:
        return []
    points: List[Dict[str, Any]] = []
    for threshold in _RISK_COVERAGE_THRESHOLDS:
        picks = [
            h
            for h in history
            if isinstance(h.get("judges"), dict)
            and isinstance(h["judges"].get(judge), dict)
            and float(h["judges"][judge].get("score") or 0) >= threshold
        ]
        n = len(picks)
        if n == 0:
            points.append(
                {
                    "threshold": threshold,
                    "n": 0,
                    "coverage": 0.0,
                    "coverage_pct": 0.0,
                    "hit_rate": None,
                    "risk": None,
                }
            )
            continue
        hits = sum(1 for h in picks if h.get("council_correct"))
        hit_rate = hits / n
        points.append(
            {
                "threshold": threshold,
                "n": n,
                "coverage": round(n / sample_size, 4),
                "coverage_pct": round(100.0 * n / sample_size, 1),
                "hit_rate": round(hit_rate, 4),
                "risk": round(1.0 - hit_rate, 4),
            }
        )
    return points


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
            "council": {
                "wins": 0,
                "losses": 0,
                "win_rate": None,
                "coverage": None,
                "coverage_pct": None,
            },
            "judges": {
                name: {
                    **_init_judge_stats(),
                    "win_rate": None,
                    "avg_pnl_pct": None,
                    "coverage": None,
                    "coverage_pct": None,
                }
                for name in JUDGES
            },
            "history": [],
            "methodology": build_methodology_payload(),
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
            score = float(judge_scores.get("score") or 0.5)
            endorsed = score >= _judge_threshold(name)
            judge_hit = council_hit if endorsed else not council_hit
            stats = judges[name]
            if judge_hit:
                stats["wins"] += 1
            else:
                stats["losses"] += 1
            stats["total_pnl_pct"] = round(stats["total_pnl_pct"] + pnl, 4)

            bin_idx = min(_CALIBRATION_BINS - 1, max(0, int(score * _CALIBRATION_BINS)))
            stats["calibration"][bin_idx]["count"] += 1
            if council_hit:
                stats["calibration"][bin_idx]["hits"] += 1

            entry["judges"][name] = {
                "score": judge_scores.get("score"),
                "confidence": judge_scores.get("confidence"),
                "pnl_pct": pnl,
                "win": judge_hit,
                "endorsed": endorsed,
                "council_correct": council_hit,
            }

        history.append(entry)

    n = len(rows)
    council_block = {
        "wins": council_wins,
        "losses": n - council_wins,
        "win_rate": round(council_wins / n, 4),
        "coverage": 1.0,
        "coverage_pct": 100.0,
        "metric_id": "council_direction_rate",
    }
    judge_blocks: Dict[str, Any] = {}
    for name in JUDGES:
        stats = judges[name]
        total = stats["wins"] + stats["losses"]
        filtered = _with_coverage(_filtered_judge_win_rate(history, name), n)
        cal = []
        for bucket in stats["calibration"]:
            count = bucket["count"]
            midpoint = round((bucket["bin"] + 0.5) / _CALIBRATION_BINS, 2)
            cal.append(
                {
                    "bin": bucket["bin"],
                    "score_lo": round(bucket["bin"] / _CALIBRATION_BINS, 2),
                    "score_hi": round((bucket["bin"] + 1) / _CALIBRATION_BINS, 2),
                    "score_mid": midpoint,
                    "count": count,
                    "hit_rate": round(bucket["hits"] / count, 4) if count else None,
                }
            )
        judge_blocks[name] = {
            "wins": stats["wins"],
            "losses": stats["losses"],
            "win_rate": filtered["win_rate"],
            "endorsed_n": filtered["n"],
            "coverage": filtered.get("coverage"),
            "coverage_pct": filtered.get("coverage_pct"),
            "threshold": filtered["min_score"],
            "metric_id": "selective_hit_rate",
            "direction_win_rate": round(stats["wins"] / total, 4) if total else None,
            "avg_pnl_pct": round(stats["total_pnl_pct"] / total, 4) if total else None,
            "total_pnl_pct": stats["total_pnl_pct"],
            "calibration": cal,
            "filtered": filtered,
            "risk_coverage": _risk_coverage_curve(history, name, sample_size=n),
        }

    return {
        "status": "success",
        "sample_size": n,
        "council": council_block,
        "judges": judge_blocks,
        "history": list(reversed(history[-24:])),
        "methodology": build_methodology_payload(),
    }


def load_backtest_from_path(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError("backtest fixture must be a JSON object")
    return run_backtest(data=data)
