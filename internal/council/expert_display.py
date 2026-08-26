"""Which council expert led a pick — signal-first, then weighted blend."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from internal.council.signal_expert import expert_from_signal_source

CANONICAL_EXPERTS = frozenset({"quant", "hype", "dark_horse", "technical"})

# Rogue = tracked-but-untracked: unresolved attribution gets its own bucket so it
# can never silently credit a real expert (legacy fallback bug) and can be
# promoted to an official expert later if it tracks well.
ROGUE_EXPERT = "rogue"

_EXPERT_LABELS = {
    "quant": "Quant",
    "hype": "Hype",
    "dark_horse": "Dark Horse",
    "technical": "Technical",
    "rogue": "Rogue",
}


def expert_label(name: str) -> str:
    return _EXPERT_LABELS.get(str(name).lower().strip(), str(name).replace("_", " ").title())


def canonical_expert_contributions(
    expert_contributions: Optional[Dict[str, Any]],
) -> Dict[str, float]:
    """Strip nested score metadata — only the four council experts."""
    if not isinstance(expert_contributions, dict):
        return {}
    out: Dict[str, float] = {}
    for name, raw in expert_contributions.items():
        if name not in CANONICAL_EXPERTS:
            continue
        try:
            out[str(name)] = float(raw)
        except (TypeError, ValueError):
            continue
    return out


def _active_signals(pick: Dict[str, Any]) -> List[str]:
    signals: List[str] = []
    for key in ("active_signals",):
        raw = pick.get(key)
        if isinstance(raw, list):
            signals.extend(str(s) for s in raw if s)
    ec = pick.get("expert_contributions")
    if isinstance(ec, dict) and isinstance(ec.get("active_signals"), list):
        signals.extend(str(s) for s in ec["active_signals"] if s)
    uniq: List[str] = []
    for sig in signals:
        if sig not in uniq:
            uniq.append(sig)
    return uniq


def leading_expert_from_signals(active_signals: List[str]) -> Optional[str]:
    """Vote by signal→expert map; None when no classifiable signals."""
    votes: Dict[str, int] = {}
    for sig in active_signals:
        expert = expert_from_signal_source(sig)
        if expert not in CANONICAL_EXPERTS:
            continue
        votes[expert] = votes.get(expert, 0) + 1
    if not votes:
        return None
    return max(votes.items(), key=lambda row: (row[1], row[0]))[0]


def weighted_expert_blend(
    expert_contributions: Optional[Dict[str, Any]],
    market_context: Optional[Dict[str, Any]] = None,
) -> Tuple[Optional[str], Dict[str, float]]:
    """Return (leader, weighted_scores) using learned council weights."""
    scores = canonical_expert_contributions(expert_contributions)
    if not scores:
        return None, {}
    weights = (market_context or {}).get("weights")
    blend_degraded = False
    if isinstance(weights, dict) and weights.get("_proxy_degraded"):
        blend_degraded = True
        weights = {}
    elif not isinstance(weights, dict):
        try:
            from internal.council.weights import effective_weights

            weights = effective_weights(market_context)
            if isinstance(weights, dict) and weights.get("_proxy_degraded"):
                blend_degraded = True
                weights = {}
        except Exception:
            blend_degraded = True
            weights = {}
    blended: Dict[str, float] = {}
    for name, score in scores.items():
        if blend_degraded:
            blended[name] = round(score, 4)
        else:
            blended[name] = round(score * float(weights.get(name, 1.0)), 4)
    if blend_degraded:
        blended["_blend_degraded"] = True  # type: ignore[assignment]
        return None, blended
    leader = max(blended.items(), key=lambda row: (row[1], row[0]))[0]
    return leader, blended


def leading_expert_for_pick(
    pick: Dict[str, Any],
    market_context: Optional[Dict[str, Any]] = None,
) -> Tuple[str, str, float]:
    """Return (expert_key, label, display_score) for UI cause-chain.

    Signal-fired experts win when classifiable signals exist; otherwise fall back
    to learned-weight blend of canonical expert scores.
    """
    signals = _active_signals(pick)
    signal_leader = leading_expert_from_signals(signals)
    scores = canonical_expert_contributions(pick.get("expert_contributions"))
    if signal_leader:
        return signal_leader, expert_label(signal_leader), scores.get(signal_leader, 0.0)
    leader, blended = weighted_expert_blend(pick.get("expert_contributions"), market_context)
    numeric = {k: v for k, v in blended.items() if k != "_blend_degraded"}
    if leader:
        return leader, expert_label(leader), numeric.get(leader, scores.get(leader, 0.0))
    return ROGUE_EXPERT, expert_label(ROGUE_EXPERT), scores.get(ROGUE_EXPERT, 0.0)


def dominant_expert_for_learning(pick: Dict[str, Any]) -> str:
    """Resolver / prediction ledger attribution — same signal-first rule."""
    leader, _, _ = leading_expert_for_pick(pick)
    return leader
