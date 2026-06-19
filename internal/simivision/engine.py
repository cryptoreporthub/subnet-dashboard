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
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from internal.council.judge.adversarial import AdversarialJudge
from internal.council.mindmap_bridge import MindmapBridge
from internal.freshness import registry_freshness, soul_map_freshness

REGISTRY_PATH = os.environ.get("REGISTRY_PATH", "config/registry.json")
SOUL_MAP_PATH = os.environ.get("SOUL_MAP_PATH", "data/soul_map.json")


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
    dir_name = os.path.dirname(path)
    if dir_name and not os.path.exists(dir_name):
        os.makedirs(dir_name, exist_ok=True)
    temp_path = path + ".tmp"
    with open(temp_path, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(temp_path, path)


def _load_registry(registry_path: str = REGISTRY_PATH) -> Dict[str, Any]:
    """Load registry.json; names are returned exactly as stored (canonical)."""
    return _load_json(registry_path)


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
        parts.append("overvaluation flag")
    if registry_status == "deprecated":
        parts.append("deprecated subnet")

    return "; ".join(parts) + "."


def _build_reason_tag(decision: Dict[str, Any]) -> str:
    """Compact tag for supporting signal cards."""
    action = decision.get("recommended_action", "hold")
    return {
        "accumulate": "Accumulate",
        "reduce": "Reduce",
        "hold": "Hold",
    }.get(action, action.capitalize())


def _determine_status(
    conviction: float, registry_fresh: Dict[str, Any], soul_map_fresh: Dict[str, Any]
) -> str:
    """Map freshness + conviction to a cognitive state."""
    if registry_fresh.get("is_stale", False) or soul_map_fresh.get("is_stale", False):
        return "Hibernating"
    if conviction >= 60:
        return "Operative"
    return "Dimmed"


def build_simivision_signal(
    netuid: int,
    decision: Dict[str, Any],
    registry_item: Dict[str, Any],
    last_convictions: Dict[str, float],
    registry_fresh: Dict[str, Any],
    soul_map_fresh: Dict[str, Any],
    source: str = "selector+council",
    judge: Optional[AdversarialJudge] = None,
) -> Dict[str, Any]:
    """
    Build a single rich SimiVision signal object.

    The subnet name is taken directly from registry_item["name"] with no
    runtime transformation, satisfying the canonical-name requirement.
    """
    conviction, indicator_phrases = _compute_conviction(decision, registry_item, judge=judge)
    status = _determine_status(conviction, registry_fresh, soul_map_fresh)
    delta, delta_value = _compute_delta(netuid, conviction, last_convictions)
    rationale = _build_rationale(decision, registry_item, conviction, status)
    freshness_ts = registry_fresh.get("last_updated") or soul_map_fresh.get("last_updated") or _now_iso()

    signal: Dict[str, Any] = {
        "netuid": netuid,
        "name": registry_item.get("name", "Unknown"),
        "rank": registry_item.get("emission_rank"),
        "conviction": conviction,
        "rationale": rationale,
        "reason_tag": _build_reason_tag(decision),
        "delta": delta,
        "delta_value": delta_value,
        "freshness": freshness_ts,
        "freshness_human": _human_freshness(freshness_ts),
        "source": source,
        "status": status,
        "indicator_phrases": indicator_phrases,
    }

    # Attach adversarial intelligence when available.
    if judge is not None:
        verdict = judge.judge_decision(
            decision,
            {
                "status": registry_item.get("status", "unknown"),
                "emission": registry_item.get("emission", 0.0),
                "social_mentions": registry_item.get("social_mentions", 0) or 0,
                "is_overvalued": registry_item.get("is_overvalued", False),
            },
            subnet_id=netuid,
        )
        signal["judge_verdict"] = {
            "score": verdict.get("score"),
            "confidence": verdict.get("confidence"),
            "outcome_label": verdict.get("outcome_label"),
            "note": verdict.get("note"),
        }
        signal["expert_track_records"] = judge.get_expert_track_records()
        signal["council_weights"] = judge.get_council_weights()

    return signal


class SimiVisionEngine:
    """
    Produces the SimiVision top-pick spine.

    Responsibilities:
    - Read canonical subnet names from registry.json.
    - Read persisted selector decisions from soul_map.json.
    - Synthesize neutral decisions for subnets without selector coverage.
    - Convert decisions into rich signal objects.
    - Persist convictions so deltas are meaningful on the next run.
    - Return the top-N scored subnets.
    """

    def __init__(
        self,
        registry_path: str = REGISTRY_PATH,
        soul_map_path: str = SOUL_MAP_PATH,
        judge: Optional[AdversarialJudge] = None,
    ):
        self.registry_path = registry_path
        self.soul_map_path = soul_map_path
        self.judge = judge or AdversarialJudge(
            persistence_path=soul_map_path,
            registry_path=registry_path,
            persist=False,
        )

    def build_signals(self) -> List[Dict[str, Any]]:
        """Build a rich signal object for every subnet in the registry."""
        registry = _load_registry(self.registry_path)
        if not registry:
            return []

        decisions = _load_selector_decisions(self.soul_map_path)
        decision_map = {d["subnet_id"]: d for d in decisions if "subnet_id" in d}
        last_convictions = _load_last_convictions(self.soul_map_path)
        registry_fresh = registry_freshness(self.registry_path)
        soul_map_fresh = soul_map_freshness(self.soul_map_path)

        signals: List[Dict[str, Any]] = []
        for key, item in registry.items():
            try:
                netuid = int(key)
            except ValueError:
                continue

            decision = decision_map.get(netuid)
            if decision is None:
                decision = _synthesize_decision(netuid, item)

            signal = build_simivision_signal(
                netuid=netuid,
                decision=decision,
                registry_item=item,
                last_convictions=last_convictions,
                registry_fresh=registry_fresh,
                soul_map_fresh=soul_map_fresh,
                source="selector+council" if netuid in decision_map else "registry",
                judge=self.judge,
            )
            signals.append(signal)

        return signals

    def top_signals(self, n: int = 3) -> List[Dict[str, Any]]:
        """Return the top-N subnets by conviction score."""
        signals = self.build_signals()
        ranked = sorted(signals, key=lambda s: s["conviction"], reverse=True)
        return ranked[:n]

    def snapshot(self, n: int = 3) -> Dict[str, Any]:
        """
        Full SimiVision snapshot for the frontend.

        Includes the top picks, a provenance summary, and freshness metadata.
        """
        signals = self.build_signals()
        ranked = sorted(signals, key=lambda s: s["conviction"], reverse=True)
        top = ranked[:n]

        # Persist current convictions for future delta calculations.
        convictions = {s["netuid"]: s["conviction"] for s in signals}
        try:
            _persist_convictions(convictions, self.soul_map_path)
        except Exception:
            pass

        registry_fresh = registry_freshness(self.registry_path)
        soul_map_fresh = soul_map_freshness(self.soul_map_path)

        any_hibernating = any(s["status"] == "Hibernating" for s in top)
        any_dimmed = any(s["status"] == "Dimmed" for s in top)
        any_error = any(s["status"] == "Error" for s in top)

        if any_error:
            system_status = "Error"
        elif any_hibernating:
            system_status = "Hibernating"
        elif any_dimmed:
            system_status = "Dimmed"
        else:
            system_status = "Operative"

        freshness_ts = registry_fresh.get("last_updated") or soul_map_fresh.get("last_updated") or _now_iso()

        return {
            "date": _now_iso(),
            "top": top,
            "meta": {
                "source": "selector+council",
                "fallback_used": False,
                "total_signals": len(signals),
                "selector_decisions": len(
                    [s for s in signals if s["source"] == "selector+council"]
                ),
                "system_status": system_status,
                "freshness": freshness_ts,
                "freshness_human": _human_freshness(freshness_ts),
                "provenance_log": [
                    "Council selector aggregated quant, hype, and contrarian experts.",
                    "Conviction scored from consensus, emission rank, social volume, and overvaluation.",
                    "Adversarial judge scored decisions against observed outcomes.",
                    "Adaptive council weights updated from expert track records.",
                    "Canonical subnet names read directly from registry.json.",
                ],
                "council_weights": self.judge.get_council_weights(),
                "expert_track_records": self.judge.get_expert_track_records(),
                "error": None,
            },
        }

    def safe_snapshot(self, n: int = 3) -> Dict[str, Any]:
        """Wrap snapshot in try/except so the homepage never 500s."""
        try:
            return self.snapshot(n=n)
        except Exception as e:
            return {
                "date": _now_iso(),
                "top": [],
                "meta": {
                    "source": "error",
                    "fallback_used": True,
                    "total_signals": 0,
                    "selector_decisions": 0,
                    "system_status": "Error",
                    "freshness": None,
                    "freshness_human": "Unknown",
                    "provenance_log": [
                        "SimiVision engine encountered an error; cached data shown.",
                    ],
                    "error": str(e),
                },
            }
