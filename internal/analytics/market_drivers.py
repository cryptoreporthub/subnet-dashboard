"""Separate staking yield from token price moves; learn what predicts price.

The learning loop grades **token price direction** only. High APY can still
wreck a wallet when the alpha token falls — this module makes that explicit and
surfaces which signals/scenarios actually predicted price moves.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from internal.subnets.apy import subnet_apy_percent, undervalued_verdict

# ponytail: fixed thresholds; upgrade path = learned cutoffs from scenario_memory
YIELD_TRAP_APY_PCT = 15.0
YIELD_TRAP_PRICE_7D_PCT = -2.0
MIN_SIGNAL_SAMPLES = 5
MIN_SCENARIO_SAMPLES = 3


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def decompose_returns(sn: Dict[str, Any]) -> Dict[str, Any]:
    """Split staking income from token price change (never conflate them)."""
    apy = subnet_apy_percent(sn)
    chg24 = _f(sn.get("price_change_24h"))
    chg7 = _f(sn.get("price_change_7d"))
    chg30 = _f(sn.get("price_change_30d"))
    weekly_yield = round(apy / 52.0, 2) if apy is not None else None
    wallet_7d = (
        round(chg7 + weekly_yield, 2)
        if weekly_yield is not None
        else round(chg7, 2)
    )
    trap_apy, trap_chg7 = _effective_yield_trap_thresholds()
    yield_trap = apy is not None and apy >= trap_apy and chg7 <= trap_chg7
    dominant = _dominant_driver(chg7, chg24, apy, yield_trap)
    warnings: List[str] = []
    if yield_trap:
        warnings.append(
            f"High staking yield ({apy:.1f}% APY) but token down {abs(chg7):.1f}% "
            "over 7d — yield income may not offset price loss"
        )
    if apy is not None and apy >= 20 and chg7 > 10:
        warnings.append(
            "Token already pumped on 7d price — high APY is staking income, not past price gain"
        )
    return {
        "staking_yield_apy": apy,
        "price_change_24h": round(chg24, 2),
        "price_change_7d": round(chg7, 2),
        "price_change_30d": round(chg30, 2),
        "weekly_yield_estimate_pct": weekly_yield,
        "wallet_impact_7d_estimate_pct": wallet_7d,
        "dominant_driver": dominant,
        "yield_trap": yield_trap,
        "valuation": undervalued_verdict(sn),
        "warnings": warnings,
        "note": (
            "APY = annual staking income on staked position. "
            "price_change_* = alpha token price move. Wallet impact ≈ price + ~1wk yield."
        ),
    }


def _dominant_driver(
    chg7: float,
    chg24: float,
    apy: Optional[float],
    yield_trap: bool,
) -> str:
    if yield_trap:
        return "yield_trap"
    if abs(chg7) >= 5:
        return "price_momentum_up" if chg7 > 0 else "price_momentum_down"
    if abs(chg24) >= 3:
        return "price_intraday"
    if apy is not None and apy >= YIELD_TRAP_APY_PCT:
        return "yield_support"
    return "neutral"


def market_driver_tags(sn: Dict[str, Any]) -> Dict[str, Any]:
    """Compact tags for scenario memory / learning loop."""
    d = decompose_returns(sn)
    return {
        "return_driver": d["dominant_driver"],
        "yield_trap": d["yield_trap"],
        "price_momentum_7d": "up" if d["price_change_7d"] >= 0 else "down",
        "staking_yield_apy": d["staking_yield_apy"],
        "price_change_7d": d["price_change_7d"],
        "wallet_impact_7d_estimate_pct": d["wallet_impact_7d_estimate_pct"],
    }


def _gradeable_resolved() -> List[Dict[str, Any]]:
    try:
        from internal.learning.predictions_store import load_predictions

        data = load_predictions()
    except Exception:
        return []
    skip = frozenset({"duplicate", "expired", "ungradeable"})
    rows: List[Dict[str, Any]] = []
    for pred in (data.get("resolved") or []):
        if not isinstance(pred, dict):
            continue
        if pred.get("outcome") in skip:
            continue
        if pred.get("actual_pct") is None:
            continue
        rows.append(pred)
    return rows


def _effective_yield_trap_thresholds() -> Tuple[float, float]:
    """Learn cutoffs from graded yield-trap-like picks when sample ≥ gate."""
    rows = _gradeable_resolved()
    apys: List[float] = []
    chg7s: List[float] = []
    for pred in rows:
        snap = pred.get("subnet_snapshot") if isinstance(pred.get("subnet_snapshot"), dict) else {}
        apy = snap.get("staking_yield_apy")
        if apy is None:
            apy = subnet_apy_percent(snap)
        chg7 = snap.get("price_change_7d")
        if chg7 is None:
            chg7 = _f(snap.get("price_change_24h"))
        else:
            chg7 = _f(chg7)
        if apy is None:
            continue
        if apy < YIELD_TRAP_APY_PCT * 0.8 or chg7 > YIELD_TRAP_PRICE_7D_PCT * 0.5:
            continue
        apys.append(float(apy))
        chg7s.append(float(chg7))
    if len(apys) < MIN_SCENARIO_SAMPLES:
        return YIELD_TRAP_APY_PCT, YIELD_TRAP_PRICE_7D_PCT
    apys.sort()
    chg7s.sort()
    mid = len(apys) // 2
    return max(12.0, apys[mid]), min(-1.5, chg7s[mid])


def _signal_bucket_stats(
    rows: List[Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    """Hit rate per active_signal when that signal fired at pick time."""
    buckets: Dict[str, Dict[str, int]] = {}
    for pred in rows:
        correct = pred.get("correct")
        if correct is None:
            outcome = str(pred.get("outcome") or "").lower()
            correct = outcome in {"hit", "correct", "win"}
        signals = pred.get("active_signals") or []
        if not isinstance(signals, list):
            continue
        for sig in signals:
            key = str(sig)
            slot = buckets.setdefault(key, {"hits": 0, "misses": 0})
            if correct:
                slot["hits"] += 1
            else:
                slot["misses"] += 1
    out: Dict[str, Dict[str, Any]] = {}
    for sig, counts in buckets.items():
        n = counts["hits"] + counts["misses"]
        if n < MIN_SIGNAL_SAMPLES:
            continue
        out[sig] = {
            "n": n,
            "hit_rate": round(counts["hits"] / n, 3),
            "hits": counts["hits"],
            "misses": counts["misses"],
            "predicts": "price_direction",
        }
    return out


def _scenario_bucket_stats() -> Dict[str, Dict[str, Any]]:
    """Which scenario tags (valuation, yield_trap, return_driver) preceded correct price calls."""
    try:
        from internal.council import scenario_memory

        snap = scenario_memory.get_memory_snapshot()
    except Exception:
        return {}
    buckets: Dict[str, Dict[str, int]] = {}
    for sc in snap.get("scenarios") or []:
        if not isinstance(sc, dict):
            continue
        outcome = str(sc.get("outcome") or "").lower()
        if outcome not in {"correct", "wrong", "hit", "miss"}:
            continue
        hit = outcome in {"correct", "hit"}
        feats = sc.get("features") or {}
        tags = [
            f"valuation:{feats.get('valuation', 'unknown')}",
            f"return_driver:{feats.get('return_driver', 'unknown')}",
            f"yield_trap:{feats.get('yield_trap', False)}",
            f"price_momentum_7d:{feats.get('price_momentum_7d', 'unknown')}",
        ]
        for tag in tags:
            slot = buckets.setdefault(tag, {"hits": 0, "misses": 0})
            if hit:
                slot["hits"] += 1
            else:
                slot["misses"] += 1
    out: Dict[str, Dict[str, Any]] = {}
    for tag, counts in buckets.items():
        n = counts["hits"] + counts["misses"]
        if n < MIN_SCENARIO_SAMPLES:
            continue
        out[tag] = {
            "n": n,
            "hit_rate": round(counts["hits"] / n, 3),
            "predicts": "price_direction",
        }
    return out


def _yield_trap_learning(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """When picks happened during yield_trap conditions, how often was price call right?"""
    hits = misses = 0
    for pred in rows:
        snap = pred.get("subnet_snapshot") or {}
        apy = snap.get("staking_yield_apy")
        if apy is None:
            apy = subnet_apy_percent(snap)
        chg7 = snap.get("price_change_7d")
        if chg7 is None:
            chg7 = _f(snap.get("price_change_24h"))
        else:
            chg7 = _f(chg7)
        if apy is None or apy < YIELD_TRAP_APY_PCT or chg7 > YIELD_TRAP_PRICE_7D_PCT:
            continue
        if pred.get("correct"):
            hits += 1
        else:
            misses += 1
    n = hits + misses
    if n < MIN_SCENARIO_SAMPLES:
        return {"n": n, "ready": False, "message": "not enough yield-trap picks graded yet"}
    return {
        "n": n,
        "ready": True,
        "hit_rate": round(hits / n, 3),
        "lesson": (
            "High APY + falling token price: council price calls were right "
            f"{round(100 * hits / n)}% of the time in this bucket"
        ),
    }


def learned_price_drivers(*, min_signal_n: int = MIN_SIGNAL_SAMPLES) -> Dict[str, Any]:
    """Aggregate learning-loop evidence for what predicted token *price* moves."""
    rows = _gradeable_resolved()
    signals = _signal_bucket_stats(rows)
    scenarios = _scenario_bucket_stats()
    yield_trap = _yield_trap_learning(rows)

    ranked_signals = sorted(
        signals.items(),
        key=lambda kv: (kv[1]["hit_rate"], kv[1]["n"]),
        reverse=True,
    )
    ranked_scenarios = sorted(
        scenarios.items(),
        key=lambda kv: (kv[1]["hit_rate"], kv[1]["n"]),
        reverse=True,
    )

    top_signals = [
        {"signal": k, **v}
        for k, v in ranked_signals[:8]
    ]
    top_scenarios = [
        {"tag": k, **v}
        for k, v in ranked_scenarios[:8]
    ]

    ready = bool(top_signals or top_scenarios or yield_trap.get("ready"))
    return {
        "ready": ready,
        "graded_predictions": len(rows),
        "min_signal_samples": min_signal_n,
        "top_price_signals": top_signals,
        "top_scenario_tags": top_scenarios,
        "yield_trap_history": yield_trap,
        "disclaimer": (
            "All hit rates grade token price direction at resolve time — "
            "staking APY is tracked separately and never treated as price appreciation."
        ),
    }


def _risk_label(decomp: Dict[str, Any], sn: Dict[str, Any]) -> str:
    if decomp["yield_trap"]:
        return "high"
    chg7 = decomp["price_change_7d"]
    vol = _f(sn.get("volume"))
    if abs(chg7) >= 15 or (vol > 0 and abs(chg7) >= 8):
        return "high"
    if abs(chg7) >= 5 or decomp["valuation"] == "rich":
        return "medium"
    return "low"


def _momentum_arrow(chg7: float) -> str:
    if chg7 >= 5:
        return "up_strong"
    if chg7 >= 1:
        return "up"
    if chg7 <= -5:
        return "down_strong"
    if chg7 <= -1:
        return "down"
    return "flat"


def _letter_grade(decomp: Dict[str, Any], risk: str) -> str:
    """Grade wallet outlook from price + yield trap — not APY alone."""
    chg7 = decomp["price_change_7d"]
    if decomp["yield_trap"]:
        return "D" if chg7 <= -10 else "C-"
    if chg7 >= 15 and risk != "high":
        return "A"
    if chg7 >= 8:
        return "B+"
    if chg7 >= 3:
        return "B"
    if chg7 >= 0:
        return "B-" if decomp["staking_yield_apy"] and decomp["staking_yield_apy"] >= 15 else "C+"
    if chg7 >= -5:
        return "C"
    if chg7 >= -12:
        return "D+"
    return "D"


def _why_lines(
    sn: Dict[str, Any],
    decomp: Dict[str, Any],
    learned: Dict[str, Any],
) -> List[str]:
    lines: List[str] = []
    apy = decomp["staking_yield_apy"]
    chg7 = decomp["price_change_7d"]

    if abs(chg7) >= 1:
        direction = "up" if chg7 > 0 else "down"
        lines.append(f"Token price {direction} {abs(chg7):.1f}% over 7d (price move — not yield)")
    else:
        lines.append("Token price flat over 7d")

    if apy is not None:
        if decomp["yield_trap"]:
            lines.append(f"Staking yield {apy:.1f}% APY — income only; token falling faster")
        elif apy >= 15:
            lines.append(f"Staking yield {apy:.1f}% APY — separate from token price")

    val = decomp["valuation"]
    if val == "deep_value":
        lines.append("Yield ahead of recent price — potential value if price catches up")
    elif val == "rich":
        lines.append("Price already ahead of yield — rich vs staking income")

    top = (learned.get("top_price_signals") or [])[:2]
    for row in top:
        if row.get("hit_rate", 0) >= 0.55:
            lines.append(
                f"Learned: '{row['signal']}' predicted price direction "
                f"{round(100 * row['hit_rate'])}% ({row['n']} picks)"
            )
            break

    yt = learned.get("yield_trap_history") or {}
    if decomp["yield_trap"] and yt.get("ready") and yt.get("hit_rate", 1) < 0.45:
        lines.append("History: yield-trap setups often fooled bullish price calls")

    return lines[:4]


def build_subnet_driver_card(sn: Dict[str, Any]) -> Dict[str, Any]:
    """Plain-English driver card — never labels APY as '7d yield' price gain."""
    decomp = decompose_returns(sn)
    learned = learned_price_drivers()
    risk = _risk_label(decomp, sn)
    grade = _letter_grade(decomp, risk)
    momentum = _momentum_arrow(decomp["price_change_7d"])
    why = _why_lines(sn, decomp, learned)

    return {
        "grade": grade,
        "momentum": momentum,
        "risk": risk,
        "why": why,
        "decomposition": decomp,
        "learned": {
            "ready": learned.get("ready"),
            "top_price_signals": learned.get("top_price_signals", [])[:3],
            "yield_trap_history": learned.get("yield_trap_history"),
        },
        "headline": _headline(grade, momentum, risk),
    }


def _headline(grade: str, momentum: str, risk: str) -> str:
    mom = {
        "up_strong": "Strong price momentum",
        "up": "Price rising",
        "down_strong": "Sharp price decline",
        "down": "Price falling",
        "flat": "Flat price",
    }.get(momentum, "Mixed")
    return f"Grade {grade} · {mom} · Risk {risk}"


def build_driver_card_for_netuid(
    netuid: int,
    subnets: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    if subnets is None:
        try:
            from server import _get_subnets_with_source

            subnets, source = _get_subnets_with_source()
        except Exception as exc:
            return {"status": "error", "netuid": netuid, "error": str(exc)}
    else:
        source = "provided"

    for sn in subnets:
        uid = sn.get("netuid", sn.get("id"))
        if uid is not None and int(uid) == int(netuid):
            card = build_subnet_driver_card(sn)
            return {
                "status": "success",
                "netuid": netuid,
                "name": sn.get("name") or f"SN{netuid}",
                "source": source,
                **card,
            }
    return {
        "status": "empty",
        "netuid": netuid,
        "message": f"SN{netuid} not in registry",
    }
