"""
SimiVision Signal Engine — Legendary Edition

Builds the rich signal object required by the SimiVision Legendary Edition:
- netuid
- name (canonical, read directly from registry.json)
- rank
- conviction (0-100)
- rationale
- delta (+/-/stable) and delta_value
- freshness
- source
- status (Operative / Dimmed / Hibernating / Error)

The engine exposes the top-N scored subnets and persists the last computed
conviction per subnet so deltas are meaningful across runs.
"""

import json
import os
import tempfile
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from internal.council.judge.adversarial import AdversarialJudge
from internal.council.mindmap_bridge import MindmapBridge
from internal.council.signals.pathfinder import PathfinderWorker
from internal.freshness import registry_freshness, soul_map_freshness

REGISTRY_PATH = os.environ.get("REGISTRY_PATH", "config/registry.json")
SOUL_MAP_PATH = os.environ.get("SOUL_MAP_PATH", "data/soul_map.json")
# Exclude top ~40 subnets by total_stake (threshold: 400,000 TAO)
STAKE_THRESHOLD_TAO = float(os.environ.get("STAKE_THRESHOLD_TAO", "400000"))

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def _parse_iso(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except Exception:
        return None

def _human_freshness(iso_timestamp: Optional[str]) -> str:
    """Return a human-readable freshness statement for an ISO timestamp."""
    if not iso_timestamp:
        return "Unknown"
    parsed = _parse_iso(iso_timestamp)
    if not parsed:
        return "Unknown"
    age = int((datetime.now(timezone.utc) - parsed).total_seconds())
    if age < 60:
        return "Just now"
    if age < 3600:
        return f"Updated {age // 60} min ago"
    if age < 86400:
        return f"Updated {age // 3600} h ago"
    return f"Updated {age // 86400} d ago"

def _load_json(path: str) -> Dict[str, Any]:
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def _save_json(path: str, data: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, temp_path = tempfile.mkstemp(dir=os.path.dirname(path) or ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(temp_path, path)
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)

def _load_registry(registry_path: str = REGISTRY_PATH) -> Dict[str, Any]:
    """Load registry.json; names are returned exactly as stored (canonical)."""
    return _load_json(registry_path)

def _filter_low_mid_cap_subnets(
    registry: Dict[str, Any], stake_threshold_tao: float = STAKE_THRESHOLD_TAO
) -> Dict[str, Any]:
    """
    Filter registry to only include low-mid cap subnets.
    Excludes subnets with total_stake >= threshold (default: 400,000 TAO).
    """
    filtered = {}
    for sid_str, data in registry.items():
        try:
            stake = data.get("staking_data", {}).get("total_stake", 0)
            if stake < stake_threshold_tao:
                filtered[sid_str] = data
        except (ValueError, TypeError):
            filtered[sid_str] = data
    return filtered

def _load_last_convictions(soul_map_path: str = SOUL_MAP_PATH) -> Dict[str, float]:
    """Load previously persisted SimiVision conviction scores keyed by netuid."""
    soul_map = _load_json(soul_map_path)
    return soul_map.get("simivision_convictions", {})

def _persist_convictions(
    convictions: Dict[int, float], soul_map_path: str = SOUL_MAP_PATH
) -> None:
    """Persist current conviction scores back to the soul map for delta tracking."""
    soul_map = _load_json(soul_map_path)
    soul_map["simivision_convictions"] = {str(k): v for k, v in convictions.items()}
    soul_map["simivision_convictions_updated_at"] = _now_iso()
    _save_json(soul_map_path, soul_map)

def _load_selector_decisions(soul_map_path: str = SOUL_MAP_PATH) -> List[Dict[str, Any]]:
    """Read the latest selector decisions persisted in the soul map."""
    soul_map = _load_json(soul_map_path)
    last_output = soul_map.get("soul_map_state", {}).get("last_selector_output", {})
    return last_output.get("decisions", [])

def _synthesize_decision(netuid: int, registry_item: Dict[str, Any]) -> Dict[str, Any]:
    """Generate a neutral decision when the Selector has not yet run for a subnet."""
    emission = registry_item.get("emission", 0.0) or 0.0
    mentions = registry_item.get("social_mentions", 0) or 0
    is_overvalued = registry_item.get("is_overvalued", False)

    quant_score = 0.85 if emission > 1.0 else 0.4 if emission < 0.2 else 0.75
    hype_score = 0.9 if mentions > 1000 else 0.3 if mentions < 100 else 0.65
    contrarian_score = 0.2 if is_overvalued else 0.8
    technical_score = 0.5

    consensus_score = round(
        quant_score * 0.3 + hype_score * 0.25 + contrarian_score * 0.2 + technical_score * 0.25, 4
    )

    if consensus_score >= 0.75:
        action = "accumulate"
    elif consensus_score <= 0.4:
        action = "reduce"
    else:
        action = "hold"

    return {
        "subnet_id": netuid,
        "consensus_score": consensus_score,
        "recommended_action": action,
        "expert_breakdown": {
            "quant": {
                "score": quant_score,
                "metrics": {
                    "emission_stability": "high" if quant_score >= 0.7 else "low",
                    "performance_index": quant_score * 100,
                },
            },
            "hype": {
                "score": hype_score,
                "sentiment": (
                    "bullish"
                    if hype_score >= 0.7
                    else "bearish"
                    if hype_score <= 0.4
                    else "neutral"
                ),
                "metrics": {
                    "social_volume": mentions,
                    "hype_index": hype_score * 100,
                },
            },
            "contrarian": {
                "score": contrarian_score,
                "signal": "sell" if is_overvalued else "buy",
                "metrics": {"contrarian_index": contrarian_score * 100},
            },
            "technical": {
                "score": technical_score,
                "signal": "hold",
                "metrics": {"active_signals": []},
            },
        },
        "synthesized": True,
    }

def _compute_conviction(
    decision: Dict[str, Any],
    registry_item: Dict[str, Any],
    judge: Optional[AdversarialJudge] = None,
) -> float:
    """
    Compute a 0-100 conviction score from selector consensus and registry metrics.

    Breakdown:
    - consensus_score * 70
    - emission rank bonus: top-10 = 15, top-25 = 10, top-50 = 5
    - social mention bonus: >1500 = 10, >1000 = 5
    - overvaluation penalty: -10 if overvalued
    - fractional tiebreaker: inverse emission_rank so lower ranks edge ahead
    - adversarial boost/penalty when a judge verdict is available
    """
    consensus = decision.get("consensus_score", 0.5)
    base = min(100.0, max(0.0, consensus * 70.0))

    rank = registry_item.get("emission_rank")
    rank_bonus = 0.0
    if isinstance(rank, int):
        if rank <= 10:
            rank_bonus = 15.0
        elif rank <= 25:
            rank_bonus = 10.0
        elif rank <= 50:
            rank_bonus = 5.0

    social = registry_item.get("social_mentions", 0) or 0
    social_bonus = 0.0
    if social > 1500:
        social_bonus = 10.0
    elif social > 1000:
        social_bonus = 5.0

    overvalued = registry_item.get("is_overvalued", False)
    penalty = 10.0 if overvalued else 0.0

    # Tiny fractional tiebreaker so top picks are ordered deterministically.
    tiebreaker = 0.0
    if isinstance(rank, int) and rank > 0:
        tiebreaker = min(0.99, 1.0 / rank)

    conviction = base + rank_bonus + social_bonus - penalty + tiebreaker

    # Indicator layer: adjust conviction based on active technical signals.
    indicator_bonus = 0.0
    indicator_phrases: List[str] = []
    breakdown = decision.get("expert_breakdown", {})
    technical = breakdown.get("technical", {})
    active_signals = technical.get("metrics", {}).get("active_signals", [])
    bullish_signals = {"rsi_oversold_reversal", "macd_bullish_cross", "stochastic_oversold_reversal", "williams_oversold_exit"}
    bearish_signals = {"rsi_overbought_reversal", "macd_bearish_cross"}
    bullish_count = sum(1 for s in active_signals if s in bullish_signals)
    bearish_count = sum(1 for s in active_signals if s in bearish_signals)
    if bullish_count > 0:
        indicator_bonus += 5.0
        indicator_phrases.extend([s.replace("_", " ") for s in active_signals if s in bullish_signals])
    if bearish_count > 0:
        indicator_bonus -= 5.0
        indicator_phrases.extend([s.replace("_", " ") for s in active_signals if s in bearish_signals])
    if bullish_count >= 2:
        indicator_bonus += 3.0
        indicator_phrases.append("bullish confluence")
    conviction += indicator_bonus

    # Adversarial layer: validated decisions get a small boost, contradicted
    # decisions get a penalty. This integrates learned outcomes into ranking.
    if judge is not None:
        verdict = judge.judge_decision(
            decision,
            {
                "status": registry_item.get("status", "unknown"),
                "emission": registry_item.get("emission", 0.0),
                "social_mentions": social,
                "is_overvalued": overvalued,
            },
            subnet_id=decision.get("subnet_id"),
        )
        label = verdict.get("outcome_label")
        confidence = verdict.get("confidence", 0.5)
        if label == "validated":
            conviction += 3.0 * confidence
        elif label == "contradicted":
            conviction -= 5.0 * confidence

    return round(min(100.0, max(0.0, conviction)), 2), indicator_phrases

def _compute_delta(
    netuid: int, conviction: float, last_convictions: Dict[str, float]
) -> tuple:
    """Return (delta_symbol, delta_value) compared to the last known conviction."""
    last = last_convictions.get(str(netuid))
    if last is None:
        return "stable", 0.0
    diff = round(conviction - last, 2)
    if abs(diff) < 0.01:
        return "stable", 0.0
    return ("+", diff) if diff > 0 else ("-", abs(diff))

def _build_rationale(
    decision: Dict[str, Any], registry_item: Dict[str, Any], conviction: float, status: str
) -> str:
    """Generate a one-line rationale from the expert breakdown and registry state."""
    if status == "Dimmed":
        return "Live but weak."

    action = decision.get("recommended_action", "hold")
    breakdown = decision.get("expert_breakdown", {})

    quant = breakdown.get("quant", {})
    hype = breakdown.get("hype", {})
    contrarian = breakdown.get("contrarian", {})
    technical = breakdown.get("technical", {})

    quant_label = (quant.get("metrics") or {}).get("emission_stability", "neutral")
    hype_label = hype.get("sentiment", "neutral")
    contrarian_label = contrarian.get("signal", "hold")

    overvalued = registry_item.get("is_overvalued", False)
    registry_status = registry_item.get("status", "unknown")

    quant_phrase = {
        "high": "strong emission stability",
        "medium": "stable emissions",
        "low": "weak emission stability",
    }.get(quant_label, f"emission stability {quant_label}")

    hype_phrase = {
        "bullish": "bullish social sentiment",
        "neutral": "neutral social sentiment",
        "bearish": "bearish social sentiment",
    }.get(hype_label, f"sentiment {hype_label}")

    contrarian_phrase = {
        "buy": "contrarian buy signal",
        "hold": "contrarian hold signal",
        "sell": "contrarian sell signal",
    }.get(contrarian_label, f"contrarian {contrarian_label}")

    if action == "accumulate":
        opener = "Strong consensus to accumulate"
    elif action == "reduce":
        opener = "Consensus favors reduction"
    else:
        opener = "Consensus is neutral"

    parts = [opener, quant_phrase, hype_phrase, contrarian_phrase]

    # Mention active indicator signals in the rationale.
    active_signals = technical.get("metrics", {}).get("active_signals", [])
    if active_signals:
        parts.append("; ".join(s.replace("_", " ") for s in active_signals))

    if overvalued:
        parts.append("overvalued")

    return " ".join(parts)

def _build_signal(
    netuid: int,
    decision: Dict[str, Any],
    registry_item: Dict[str, Any],
    last_convictions: Dict[str, float],
    judge: Optional[AdversarialJudge] = None,
) -> Dict[str, Any]:
    """Build a single SimiVision signal object for a subnet."""
    conviction, indicator_phrases = _compute_conviction(decision, registry_item, judge)
    delta, delta_value = _compute_delta(netuid, conviction, last_convictions)
    status = "Operative" if registry_item.get("status") == "active" else "Dimmed"

    return {
        "netuid": netuid,
        "name": registry_item.get("name", f"Subnet {netuid}"),
        "rank": netuid,
        "conviction": conviction,
        "rationale": _build_rationale(decision, registry_item, conviction, status),
        "delta": delta,
        "delta_value": delta_value,
        "freshness": _human_freshness(registry_item.get("last_updated")),
        "source": "registry",
        "status": status,
        "indicator_phrases": indicator_phrases,
    }

def _get_simivision_signals(
    registry: Dict[str, Any],
    soul_map_path: str = SOUL_MAP_PATH,
    judge: Optional[AdversarialJudge] = None,
) -> List[Dict[str, Any]]:
    """Generate SimiVision signals for all subnets in the registry."""
    last_convictions = _load_last_convictions(soul_map_path)
    selector_decisions = _load_selector_decisions(soul_map_path)
    decisions_by_subnet = {d["subnet_id"]: d for d in selector_decisions}

    signals = []
    for netuid_str, registry_item in registry.items():
        try:
            netuid = int(netuid_str)
        except (ValueError, TypeError):
            continue

        decision = decisions_by_subnet.get(netuid)
        if decision is None:
            decision = _synthesize_decision(netuid, registry_item)

        signal = _build_signal(netuid, decision, registry_item, last_convictions, judge)
        signals.append(signal)

    # Sort by conviction descending
    signals.sort(key=lambda s: s["conviction"], reverse=True)
    return signals

class SimiVisionEngine:
    """Engine for generating SimiVision signals."""

    def __init__(
        self,
        registry_path: str = REGISTRY_PATH,
        soul_map_path: str = SOUL_MAP_PATH,
        stake_threshold_tao: float = STAKE_THRESHOLD_TAO,
    ):
        self.registry_path = registry_path
        self.soul_map_path = soul_map_path
        self.stake_threshold_tao = stake_threshold_tao

    def get_signals(self) -> List[Dict[str, Any]]:
        """Generate and return SimiVision signals for low-mid cap subnets."""
        registry = _load_registry(self.registry_path)
        filtered_registry = _filter_low_mid_cap_subnets(registry, self.stake_threshold_tao)
        return _get_simivision_signals(filtered_registry, self.soul_map_path)

    def get_signal(self, netuid: int) -> Optional[Dict[str, Any]]:
        """Get a single SimiVision signal for a specific subnet."""
        registry = _load_registry(self.registry_path)
        filtered_registry = _filter_low_mid_cap_subnets(registry, self.stake_threshold_tao)
        if str(netuid) not in filtered_registry:
            return None
        signals = self.get_signals()
        return next((s for s in signals if s["netuid"] == netuid), None)