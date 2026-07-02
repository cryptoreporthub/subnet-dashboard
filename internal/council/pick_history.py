"""Pick-of-the-Hour outcome tracking + success metric.

Tracks each Pick of the Hour selection with its entry price, selection
timestamp, and trigger reason. When a new pick replaces the old one, the
old pick's outcome is computed against the *median* of all subnets over the
same period so we can grade whether the pick outperformed the market.

A pick is **successful** when its absolute return beats the median subnet
return over its tenure (primary metric). Positive absolute return is a
secondary, weaker signal.

Persistence lives in ``data/pick_history.json`` (ephemeral on Fly.io; the
file is created on first write via ``ensure_data_dir``). The store shape is::

    {
      "active": {                 # currently-tenured pick (or null)
        "netuid", "name", "selected_at", "entry_price",
        "trigger_reason", "entry_prices_snapshot": {netuid: price, ...}
      },
      "history": [                # most-recent-first finalized picks
        {
          "netuid", "name", "selected_at", "replaced_at",
          "entry_price", "exit_price",
          "absolute_return", "median_subnet_return", "percentile_rank",
          "success": bool, "trigger_reason"
        }, ...
      ]
    }
"""

from __future__ import annotations

import json
import logging
import os
import statistics
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from internal.council.weights import load_weights, save_weights
from internal.file_utils import ensure_data_dir

logger = logging.getLogger(__name__)

# Learning-rate constants, kept in sync with resolver.py so both paths
# (prediction-resolution and pick-outcome) move weights at similar pace.
_LEARNING_DELTA_CORRECT = 0.02
_LEARNING_DELTA_WRONG = -0.03
_LEARNING_MIN_WEIGHT = 0.1
_LEARNING_MAX_WEIGHT = 2.0

PICK_HISTORY_PATH = os.environ.get("PICK_HISTORY_PATH", os.path.join("data", "pick_history.json"))

# Cap the retained finalized-pick history so the file stays bounded on an
# ephemeral Fly.io volume.
_MAX_HISTORY = 100


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load() -> Dict[str, Any]:
    """Load the pick-history store, returning a well-formed default on miss."""
    try:
        with open(PICK_HISTORY_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            data.setdefault("active", None)
            data.setdefault("history", [])
            return data
    except Exception:
        pass
    return {"active": None, "history": []}


def _save(store: Dict[str, Any]) -> None:
    ensure_data_dir()
    tmp = PICK_HISTORY_PATH + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(store, fh, indent=2)
        os.replace(tmp, PICK_HISTORY_PATH)
    except Exception as exc:
        logger.warning("pick_history save failed: %s", exc)


def _price_map(subnets: List[Dict[str, Any]]) -> Dict[Any, float]:
    """Snapshot {netuid: price} for every subnet with a usable price."""
    out: Dict[Any, float] = {}
    for sn in subnets or []:
        if not isinstance(sn, dict):
            continue
        nu = sn.get("netuid")
        if nu is None:
            continue
        try:
            price = float(sn.get("price", 0) or 0)
        except (TypeError, ValueError):
            continue
        if price > 0:
            out[nu] = price
    return out


def _returns_vs_snapshot(
    subnets: List[Dict[str, Any]], snapshot: Dict[Any, float]
) -> Tuple[List[float], Dict[Any, float]]:
    """Return (per-subnet % returns vs snapshot, current price map)."""
    current = _price_map(subnets)
    returns: List[float] = []
    for nu, entry in snapshot.items():
        cur = current.get(nu)
        if not cur or not entry:
            continue
        returns.append((cur - entry) / entry * 100.0)
    return returns, current


def _median(values: List[float]) -> float:
    if not values:
        return 0.0
    try:
        return float(statistics.median(values))
    except statistics.StatisticsError:
        return 0.0


def _percentile_rank(pick_return: float, all_returns: List[float]) -> float:
    """Where ``pick_return`` ranks among ``all_returns`` (0-100, higher=better)."""
    if not all_returns:
        return 50.0
    below = sum(1 for r in all_returns if r < pick_return)
    return round(below / len(all_returns) * 100.0, 1)


def _trigger_reason(sn: Dict[str, Any], indicators: Optional[Dict[str, Any]] = None) -> str:
    """Derive a short human-readable reason for why a subnet was selected."""
    chg = float(sn.get("price_change_24h", 0) or 0)
    vol = float(sn.get("volume", 0) or 0)
    apy = float(sn.get("apy", 0) or 0)
    emission = float(sn.get("emission", 0) or 0)

    reasons: List[str] = []
    ind = indicators if isinstance(indicators, dict) else {}
    rsi = float((ind.get("rsi") or {}).get("value", 50) or 50) if ind else 50.0
    macd = ind.get("macd") if ind else None
    macd_cross = macd.get("crossover") if isinstance(macd, dict) else None

    if chg >= 5:
        reasons.append(f"{chg:.2f}% 24h momentum")
    elif chg <= -5:
        reasons.append(f"{chg:.2f}% 24h drawdown")
    if apy > 20 and emission > 1:
        reasons.append(f"{apy:.1f}% APY yield")
    if rsi < 30:
        reasons.append("RSI oversold breakout")
    elif rsi > 70:
        reasons.append("RSI overbought")
    if macd_cross == "bullish":
        reasons.append("MACD bullish cross")
    elif macd_cross == "bearish":
        reasons.append("MACD bearish cross")
    if vol > 1_000_000:
        reasons.append("volume spike")
    if not reasons:
        reasons.append(f"{chg:+.2f}% 24h move")
    return " · ".join(reasons[:2])


def _nudge_weights_from_pick_outcome(
    success: bool, expert_contributions: Dict[str, float]
) -> None:
    """Nudge Council expert weights based on a finalized pick outcome.

    Contribution-weighted update: an expert that scored 0.77 gets ~3× the
    nudge of one that scored 0.25, because the delta is scaled by the
    contribution value (capped at 1.0).
    """
    if not expert_contributions:
        return
    weights = load_weights()
    changed = False
    for expert, contrib in expert_contributions.items():
        if expert not in weights:
            continue
        contrib = max(0.0, min(1.0, float(contrib)))
        if contrib <= 0.0:
            continue
        # Scale the base delta by the expert's contribution to the pick.
        delta = (_LEARNING_DELTA_CORRECT if success else _LEARNING_DELTA_WRONG) * contrib
        old_weight = weights[expert]
        new_weight = max(
            _LEARNING_MIN_WEIGHT,
            min(_LEARNING_MAX_WEIGHT, old_weight + delta),
        )
        new_weight = round(new_weight, 4)
        if abs(new_weight - old_weight) > 0.0001:
            weights[expert] = new_weight
            changed = True
            # Log to trace store.
            try:
                from internal.council.trace_store import get_trace_store
                store = get_trace_store()
                store.add_learning_update(
                    run_id=None,
                    expert=expert,
                    old_weight=old_weight,
                    new_weight=new_weight,
                    reason=f"pick_{'win' if success else 'loss'}_contrib_{contrib:.2f}",
                )
            except Exception:
                pass
    if changed:
        save_weights(weights)


def _finalize(
    active: Dict[str, Any],
    subnets: List[Dict[str, Any]],
    replaced_at: str,
) -> Dict[str, Any]:
    """Compute the outcome record for a pick whose tenure just ended."""
    snapshot = active.get("entry_prices_snapshot") or {}
    returns, current = _returns_vs_snapshot(subnets, snapshot)
    entry_price = float(active.get("entry_price", 0) or 0)
    exit_price = current.get(active.get("netuid"), entry_price)
    absolute_return = 0.0
    if entry_price > 0 and exit_price > 0:
        absolute_return = (exit_price - entry_price) / entry_price * 100.0
    median_return = _median(returns)
    # Rank the pick's own return among ALL subnets' returns (inclusive).
    rank_returns = list(returns)
    percentile = _percentile_rank(absolute_return, rank_returns)
    success = absolute_return > median_return

    # Feed the outcome back into the learning loop so the experts that drove
    # this pick are nudged up (success) or down (failure) proportionally to
    # their contribution.
    expert_contributions = active.get("expert_contributions") or {}
    try:
        _nudge_weights_from_pick_outcome(success, expert_contributions)
    except Exception as exc:
        logger.warning("_nudge_weights_from_pick_outcome failed: %s", exc)

    return {
        "netuid": active.get("netuid"),
        "name": active.get("name"),
        "selected_at": active.get("selected_at"),
        "replaced_at": replaced_at,
        "entry_price": round(entry_price, 6),
        "exit_price": round(exit_price, 6),
        "absolute_return": round(absolute_return, 2),
        "median_subnet_return": round(median_return, 2),
        "percentile_rank": percentile,
        "success": bool(success),
        "trigger_reason": active.get("trigger_reason"),
    }


def record_pick(
    pick: Dict[str, Any],
    subnets: List[Dict[str, Any]],
    indicators: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Track a Pick of the Hour selection and return the enriched pick.

    Called on every render/API hit for the current #1 hourly pick. Idempotent
    for the same netuid: it only updates the live ``price_change_since_selection``
    + vs-market fields. When the #1 netuid changes, the previous pick's tenure
    is finalized (outcome computed vs the median subnet) and appended to
    ``history`` before the new pick is recorded.

    The returned dict is the input ``pick`` augmented with:
      ``selected_at``, ``entry_price``, ``trigger_reason``,
      ``price_change_since_selection``, ``current_price``,
      ``median_subnet_return``, ``vs_market``, ``success_so_far``.
    """
    if not isinstance(pick, dict):
        return pick
    netuid = pick.get("netuid")
    if netuid is None:
        subnet = pick.get("subnet") if isinstance(pick.get("subnet"), dict) else {}
        netuid = subnet.get("netuid")
        name = subnet.get("name")
    else:
        name = pick.get("name")
    if netuid is None:
        return pick

    sn = next((s for s in (subnets or []) if s.get("netuid") == netuid), {})
    current_price = float(sn.get("price", 0) or 0)
    snapshot = _price_map(subnets)

    store = _load()
    active = store.get("active") if isinstance(store.get("active"), dict) else None
    now_iso = _now_iso()

    # Same pick still tenured: refresh live fields only.
    if active and active.get("netuid") == netuid:
        entry_price = float(active.get("entry_price", 0) or 0)
        # Refresh the price snapshot lazily so vs-market stays live even if the
        # subnet set changed; keep the original entry prices for the pick itself.
        returns, _ = _returns_vs_snapshot(subnets, active.get("entry_prices_snapshot") or {})
        median_return = _median(returns)
        change_since = 0.0
        if entry_price > 0 and current_price > 0:
            change_since = (current_price - entry_price) / entry_price * 100.0
        enriched = dict(pick)
        enriched.update({
            "selected_at": active.get("selected_at"),
            "entry_price": round(entry_price, 6),
            "trigger_reason": active.get("trigger_reason"),
            "current_price": round(current_price, 6),
            "price_change_since_selection": round(change_since, 2),
            "median_subnet_return": round(median_return, 2),
            "vs_market": round(change_since - median_return, 2),
            "success_so_far": bool(change_since > median_return),
        })
        return enriched

    # New pick: finalize the previous one, then record this one.
    history: List[Dict[str, Any]] = list(store.get("history") or [])
    if active:
        try:
            history.insert(0, _finalize(active, subnets, now_iso))
            history = history[:_MAX_HISTORY]
        except Exception as exc:
            logger.warning("pick_history finalize failed: %s", exc)

    entry_price = current_price if current_price > 0 else 1.0
    reason = _trigger_reason(sn, indicators)
    # Persist the expert contributions that drove this pick so _finalize can
    # later nudge each expert proportionally to their contribution.
    expert_contributions = pick.get("expert_contributions") or {}
    store["active"] = {
        "netuid": netuid,
        "name": name,
        "selected_at": now_iso,
        "entry_price": round(entry_price, 6),
        "trigger_reason": reason,
        "expert_contributions": expert_contributions,
        "entry_prices_snapshot": snapshot,
    }
    store["history"] = history
    _save(store)

    enriched = dict(pick)
    enriched.update({
        "selected_at": now_iso,
        "entry_price": round(entry_price, 6),
        "trigger_reason": reason,
        "current_price": round(current_price, 6),
        "price_change_since_selection": 0.0,
        "median_subnet_return": 0.0,
        "vs_market": 0.0,
        "success_so_far": True,
    })
    return enriched


def get_history(limit: int = 20) -> Dict[str, Any]:
    """Return the active pick + recent finalized history + aggregate stats."""
    store = _load()
    history: List[Dict[str, Any]] = list(store.get("history") or [])
    finalized = [h for h in history if isinstance(h, dict)]
    total = len(finalized)
    wins = sum(1 for h in finalized if h.get("success"))
    success_rate = round(wins / total * 100.0, 1) if total else 0.0
    return {
        "active": store.get("active"),
        "history": finalized[:limit],
        "stats": {
            "total": total,
            "wins": wins,
            "losses": total - wins,
            "success_rate": success_rate,
        },
    }


def reset_for_tests(path: Optional[str] = None) -> None:
    """Test hook: redirect persistence to a temp path (call before tests)."""
    global PICK_HISTORY_PATH
    if path is not None:
        PICK_HISTORY_PATH = path
