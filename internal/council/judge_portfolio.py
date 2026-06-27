"""
3-Judge paper portfolios for the Council engine.

Three judge identities trade simulated TAO positions:
- Evidence Council: technical-score-driven, conservative longs.
- Adversarial Council: contrarian shorts against consensus.
- Chaos Council: random exploration from the middle of the pack.

Portfolios persist to ``data/judge_portfolios.json``. Judge influence weights
persist to ``data/soul_map.json`` under ``judge_portfolio_weights`` so
outperformance feeds back into the Council learning loop.
"""

from __future__ import annotations

import json
import math
import os
import random
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from internal.council.state_vector import score_subnet_for_day
from internal.council.weights import _load_raw as _load_soul_map, _save_raw as _save_soul_map

JUDGE_PORTFOLIOS_PATH = os.path.join("data", "judge_portfolios.json")
SOUL_MAP_PATH = os.path.join("data", "soul_map.json")

JUDGES: Dict[str, Dict[str, Any]] = {
    "evidence": {
        "judge_id": "evidence",
        "judge_name": "Evidence Council",
        "judge_description": "Technical-indicator-driven, conservative/convergent picks based on signal strength.",
    },
    "adversarial": {
        "judge_id": "adversarial",
        "judge_name": "Adversarial Council",
        "judge_description": "Contrarian judge that bets against consensus and shorts overvalued subnets.",
    },
    "chaos": {
        "judge_id": "chaos",
        "judge_name": "Chaos Council",
        "judge_description": "Random/high-variance explorer that probes the edge of the subnet universe.",
    },
}

DEFAULT_POSITION_SIZE = 1.0


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_json(path: str, default: Any) -> Any:
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return default


def _save_json(path: str, data: Any) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value or default)
    except Exception:
        return default


class JudgePortfolioManager:
    """Manages paper portfolios for the three Council judges."""

    def __init__(self, path: Optional[str] = None, soul_map_path: Optional[str] = None):
        self.path = path or JUDGE_PORTFOLIOS_PATH
        self.soul_map_path = soul_map_path or SOUL_MAP_PATH
        self._portfolios: Dict[str, Dict[str, Any]] = self._load_state()
        self._ensure_judges()

    def _load_state(self) -> Dict[str, Dict[str, Any]]:
        data = _load_json(self.path, {"portfolios": {}})
        if not isinstance(data, dict):
            data = {"portfolios": {}}
        return data.get("portfolios", {})

    def _save_state(self) -> None:
        _save_json(self.path, {"portfolios": self._portfolios, "last_updated": _now_iso()})

    def _ensure_judges(self) -> None:
        for judge_id, meta in JUDGES.items():
            if judge_id not in self._portfolios:
                self._portfolios[judge_id] = {
                    **meta,
                    "positions": [],
                    "closed_positions": [],
                    "stats": self._empty_stats(),
                    "last_updated": _now_iso(),
                }

    def _empty_stats(self) -> Dict[str, Any]:
        return {
            "total_trades": 0,
            "wins": 0,
            "losses": 0,
            "win_rate": 0.0,
            "total_return_pct": 0.0,
            "avg_return_per_trade": 0.0,
            "sharpe_ratio": 0.0,
            "max_drawdown": 0.0,
            "profit_factor": 0.0,
        }

    def _compute_stats(self, portfolio: Dict[str, Any]) -> Dict[str, Any]:
        closed = portfolio.get("closed_positions", [])
        if not closed:
            return self._empty_stats()

        returns = [_safe_float(p.get("realized_return_pct")) for p in closed]
        wins = sum(1 for r in returns if r > 0)
        losses = sum(1 for r in returns if r < 0)
        breakevens = len(closed) - wins - losses

        total_return = sum(returns)
        avg_return = total_return / len(closed)

        gross_wins = sum(r for r in returns if r > 0)
        gross_losses = abs(sum(r for r in returns if r < 0))
        profit_factor = round(gross_wins / gross_losses, 4) if gross_losses > 0 else round(gross_wins, 4)

        std_return = math.sqrt(sum((r - avg_return) ** 2 for r in returns) / len(returns)) if len(returns) > 1 else 0.0
        sharpe_ratio = round(avg_return / std_return, 4) if std_return > 0 else round(avg_return, 4)

        # Max drawdown from cumulative returns.
        cumulative = 0.0
        peak = 0.0
        max_dd = 0.0
        for r in returns:
            cumulative += r
            peak = max(peak, cumulative)
            max_dd = max(max_dd, peak - cumulative)

        return {
            "total_trades": len(closed),
            "wins": wins,
            "losses": losses,
            "win_rate": round(wins / len(closed), 4) if closed else 0.0,
            "total_return_pct": round(total_return, 4),
            "avg_return_per_trade": round(avg_return, 4),
            "sharpe_ratio": sharpe_ratio,
            "max_drawdown": round(max_dd, 4),
            "profit_factor": profit_factor,
        }

    def _outcome(self, return_pct: float) -> str:
        if return_pct > 0:
            return "win"
        if return_pct < 0:
            return "loss"
        return "breakeven"

    def open_position(
        self,
        judge_id: str,
        netuid: Any,
        subnet_name: str,
        entry_price: float,
        direction: str,
        entry_signal: str,
        size: float = DEFAULT_POSITION_SIZE,
    ) -> Dict[str, Any]:
        """Open a new paper position for a judge."""
        if judge_id not in JUDGES:
            raise ValueError(f"Unknown judge_id: {judge_id}")
        if direction not in {"long", "short"}:
            raise ValueError("direction must be 'long' or 'short'")

        portfolio = self._portfolios[judge_id]
        position = {
            "position_id": str(uuid.uuid4()),
            "netuid": netuid,
            "subnet_name": subnet_name,
            "entry_price": _safe_float(entry_price),
            "entry_time": _now_iso(),
            "direction": direction,
            "size": _safe_float(size, DEFAULT_POSITION_SIZE),
            "entry_signal": entry_signal,
            "current_return_pct": 0.0,
        }
        portfolio["positions"].append(position)
        portfolio["last_updated"] = _now_iso()
        self._save_state()
        return position

    def close_position(self, position_id: str, exit_price: float) -> Optional[Dict[str, Any]]:
        """Close an open position and move it to closed_positions."""
        exit_price = _safe_float(exit_price)
        for judge_id, portfolio in self._portfolios.items():
            for idx, pos in enumerate(portfolio["positions"]):
                if pos.get("position_id") == position_id:
                    entry = _safe_float(pos.get("entry_price"))
                    direction = pos.get("direction", "long")
                    if entry <= 0:
                        realized = 0.0
                    elif direction == "long":
                        realized = (exit_price - entry) / entry * 100
                    else:
                        realized = (entry - exit_price) / entry * 100

                    closed = dict(pos)
                    closed["exit_price"] = exit_price
                    closed["exit_time"] = _now_iso()
                    closed["realized_return_pct"] = round(realized, 4)
                    closed["outcome"] = self._outcome(realized)
                    portfolio["closed_positions"].append(closed)
                    portfolio["positions"].pop(idx)
                    portfolio["stats"] = self._compute_stats(portfolio)
                    portfolio["last_updated"] = _now_iso()
                    self._save_state()
                    return closed
        return None

    def update_unrealized(self, current_prices: Dict[Any, float]) -> None:
        """Refresh current_return_pct for all open positions."""
        for portfolio in self._portfolios.values():
            for pos in portfolio["positions"]:
                entry = _safe_float(pos.get("entry_price"))
                uid = pos.get("netuid")
                exit_price = _safe_float(current_prices.get(uid), 0.0)
                if entry <= 0 or exit_price <= 0:
                    pos["current_return_pct"] = 0.0
                    continue
                if pos.get("direction") == "long":
                    pos["current_return_pct"] = round((exit_price - entry) / entry * 100, 4)
                else:
                    pos["current_return_pct"] = round((entry - exit_price) / entry * 100, 4)
            portfolio["last_updated"] = _now_iso()
        self._save_state()

    def rebalance(
        self,
        judge_id: str,
        netuid: Any,
        direction: str,
        confidence: float,
    ) -> Optional[Dict[str, Any]]:
        """Adjust position size based on conviction for an existing open position."""
        if judge_id not in self._portfolios:
            return None
        confidence = _safe_float(confidence, 0.5)
        for pos in self._portfolios[judge_id]["positions"]:
            if pos.get("netuid") == netuid and pos.get("direction") == direction:
                # Scale size linearly with confidence, clamped between 0.5 and 3.0 TAO.
                new_size = round(min(3.0, max(0.5, DEFAULT_POSITION_SIZE * confidence * 2)), 4)
                pos["size"] = new_size
                pos["last_rebalanced"] = _now_iso()
                self._portfolios[judge_id]["last_updated"] = _now_iso()
                self._save_state()
                return pos
        return None

    def get_portfolio(self, judge_id: str) -> Optional[Dict[str, Any]]:
        """Return a single judge portfolio with fresh stats."""
        if judge_id not in self._portfolios:
            return None
        portfolio = self._portfolios[judge_id]
        portfolio["stats"] = self._compute_stats(portfolio)
        return portfolio

    def get_all_portfolios(self) -> Dict[str, Any]:
        """Return all judge portfolios plus a leaderboard."""
        for portfolio in self._portfolios.values():
            portfolio["stats"] = self._compute_stats(portfolio)
        return {
            "portfolios": self._portfolios,
            "leaderboard": self.get_leaderboard(),
            "last_updated": _now_iso(),
        }

    def get_leaderboard(self) -> List[Dict[str, Any]]:
        """Compare all judges side-by-side by return, win rate, Sharpe and PF."""
        rows: List[Dict[str, Any]] = []
        for judge_id, portfolio in self._portfolios.items():
            stats = self._compute_stats(portfolio)
            rows.append({
                "judge_id": judge_id,
                "judge_name": portfolio.get("judge_name", judge_id),
                "total_return_pct": stats["total_return_pct"],
                "win_rate": stats["win_rate"],
                "sharpe_ratio": stats["sharpe_ratio"],
                "profit_factor": stats["profit_factor"],
                "total_trades": stats["total_trades"],
            })
        # Sort by total return, then win rate, then Sharpe.
        rows.sort(key=lambda r: (r["total_return_pct"], r["win_rate"], r["sharpe_ratio"]), reverse=True)
        for i, row in enumerate(rows, start=1):
            row["rank"] = i
        return rows

    def daily_judge_action(
        self,
        judge_id: str,
        subnets: List[Dict[str, Any]],
        predictions: List[Dict[str, Any]],
        prices: Dict[Any, float],
    ) -> Dict[str, Any]:
        """Execute one daily action cycle for a single judge."""
        if judge_id not in JUDGES:
            raise ValueError(f"Unknown judge_id: {judge_id}")

        if judge_id == "evidence":
            return self._evidence_action(subnets, prices)
        if judge_id == "adversarial":
            return self._adversarial_action(subnets, predictions, prices)
        return self._chaos_action(subnets, prices)

    def _score_subnets(self, subnets: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Score subnets using the day state vector."""
        market_context = {"tao_change_24h": 0.0}
        scored = []
        for sn in subnets:
            try:
                score = score_subnet_for_day(sn, market_context)
            except Exception:
                score = {"total_score": 50.0, "confidence": 0.5}
            scored.append({
                "netuid": sn.get("netuid"),
                "name": sn.get("name"),
                "price": _safe_float(sn.get("price")),
                "price_change_24h": _safe_float(sn.get("price_change_24h")),
                "total_score": _safe_float(score.get("total_score"), 50.0),
                "confidence": _safe_float(score.get("confidence"), 0.5),
            })
        scored.sort(key=lambda x: x["total_score"], reverse=True)
        return scored

    def _evidence_action(self, subnets: List[Dict[str, Any]], prices: Dict[Any, float]) -> Dict[str, Any]:
        """Open long positions on the top-3 technical-score subnets."""
        scored = self._score_subnets(subnets)
        picks = scored[:3]
        opened = []
        for pick in picks:
            uid = pick["netuid"]
            price = prices.get(uid, pick["price"])
            if price <= 0:
                continue
            pos = self.open_position(
                judge_id="evidence",
                netuid=uid,
                subnet_name=pick["name"] or f"SN{uid}",
                entry_price=price,
                direction="long",
                entry_signal=f"top technical score {pick['total_score']:.1f}",
                size=DEFAULT_POSITION_SIZE,
            )
            opened.append(pos)
        return {"judge_id": "evidence", "action": "open_longs", "opened": opened}

    def _adversarial_action(
        self,
        subnets: List[Dict[str, Any]],
        predictions: List[Dict[str, Any]],
        prices: Dict[Any, float],
    ) -> Dict[str, Any]:
        """Short the bottom-3 scored subnets (contrarian / overvalued)."""
        scored = self._score_subnets(subnets)
        picks = scored[-3:] if len(scored) >= 3 else scored
        opened = []
        for pick in picks:
            uid = pick["netuid"]
            price = prices.get(uid, pick["price"])
            if price <= 0:
                continue
            pos = self.open_position(
                judge_id="adversarial",
                netuid=uid,
                subnet_name=pick["name"] or f"SN{uid}",
                entry_price=price,
                direction="short",
                entry_signal=f"contrarian short on low score {pick['total_score']:.1f}",
                size=DEFAULT_POSITION_SIZE,
            )
            opened.append(pos)
        return {"judge_id": "adversarial", "action": "open_shorts", "opened": opened}

    def _chaos_action(self, subnets: List[Dict[str, Any]], prices: Dict[Any, float]) -> Dict[str, Any]:
        """Randomly pick from the middle 50% of subnets with random direction."""
        scored = self._score_subnets(subnets)
        n = len(scored)
        if n == 0:
            return {"judge_id": "chaos", "action": "noop", "opened": []}

        lower = int(n * 0.25)
        upper = int(n * 0.75)
        middle = scored[lower:upper]
        if not middle:
            middle = scored

        count = min(3, len(middle))
        picks = random.sample(middle, count) if len(middle) > count else middle
        opened = []
        for pick in picks:
            uid = pick["netuid"]
            price = prices.get(uid, pick["price"])
            if price <= 0:
                continue
            direction = random.choice(["long", "short"])
            pos = self.open_position(
                judge_id="chaos",
                netuid=uid,
                subnet_name=pick["name"] or f"SN{uid}",
                entry_price=price,
                direction=direction,
                entry_signal="chaos exploration from middle 50%",
                size=DEFAULT_POSITION_SIZE,
            )
            opened.append(pos)
        return {"judge_id": "chaos", "action": "random_explore", "opened": opened}

    def run_all_daily_actions(
        self,
        subnets: List[Dict[str, Any]],
        predictions: List[Dict[str, Any]],
        prices: Dict[Any, float],
    ) -> Dict[str, Any]:
        """Run the daily action cycle for all three judges."""
        results = {}
        for judge_id in JUDGES:
            results[judge_id] = self.daily_judge_action(judge_id, subnets, predictions, prices)
        self.adjust_judge_weights()
        return {"actions": results, "leaderboard": self.get_leaderboard(), "last_updated": _now_iso()}

    def adjust_judge_weight(self, judge_id: str) -> None:
        """Boost or reduce a judge's influence weight based on relative return."""
        if judge_id not in self._portfolios:
            return

        leaderboard = self.get_leaderboard()
        returns = {row["judge_id"]: row["total_return_pct"] for row in leaderboard}
        if not returns:
            return

        avg_return = sum(returns.values()) / len(returns)
        judge_return = returns.get(judge_id, 0.0)
        delta = 0.05 if judge_return >= avg_return else -0.05

        soul_map = _load_soul_map(self.soul_map_path)
        weights = soul_map.setdefault("judge_portfolio_weights", {})
        if not isinstance(weights, dict):
            weights = {}
            soul_map["judge_portfolio_weights"] = weights
        current = _safe_float(weights.get(judge_id), 1.0)
        weights[judge_id] = round(min(2.0, max(0.1, current + delta)), 4)
        _save_soul_map(soul_map, self.soul_map_path)

    def adjust_judge_weights(self) -> None:
        """Adjust all judge weights after a daily cycle."""
        for judge_id in JUDGES:
            self.adjust_judge_weight(judge_id)

    def get_judge_weights(self) -> Dict[str, float]:
        """Return current judge portfolio weights from soul_map.json."""
        soul_map = _load_soul_map(self.soul_map_path)
        weights = soul_map.get("judge_portfolio_weights", {})
        if not isinstance(weights, dict):
            weights = {}
        return {judge_id: _safe_float(weights.get(judge_id), 1.0) for judge_id in JUDGES}
