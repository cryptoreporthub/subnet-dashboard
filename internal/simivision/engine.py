"""
SimiVision Engine — builds rich signal objects for the Legendary Edition UI.

Phase 0: integrates with the MindmapBridge for conviction decay and
outcome-gated recommendations.
"""

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from internal.council.judge.adversarial import AdversarialJudge
from internal.council.mindmap_bridge import MindmapBridge


REGISTRY_PATH = os.environ.get("REGISTRY_PATH", "config/registry.json")
SOUL_MAP_PATH = os.environ.get("SOUL_MAP_PATH", "data/soul_map.json")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_json(path: str) -> Dict[str, Any]:
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _load_selector_decisions() -> List[Dict[str, Any]]:
    """Load the latest selector decisions from the soul map."""
    soul_map = _load_json(SOUL_MAP_PATH)
    last_output = soul_map.get("soul_map_state", {}).get("last_selector_output", {})
    return last_output.get("decisions", [])


def _synthesize_decision(
    netuid: int, registry_item: Dict[str, Any]
) -> Dict[str, Any]:
    """Synthesize a decision for a subnet that has no selector output."""
    emission = registry_item.get("emission", 0.0) or 0.0
    social = registry_item.get("social_mentions", 0) or 0
    is_overvalued = registry_item.get("is_overvalued", False)

    quant_score = 0.85 if emission > 1.0 else 0.4 if emission < 0.2 else 0.75
    hype_score = 0.9 if social > 1000 else 0.3 if social < 100 else 0.65
    contrarian_score = 0.2 if is_overvalued else 0.8

    consensus = (quant_score + hype_score + contrarian_score) / 3
    if consensus >= 0.7:
        action = "accumulate"
    elif consensus <= 0.4:
        action = "reduce"
    else:
        action = "hold"

    return {
        "subnet_id": netuid,
        "consensus_score": round(consensus, 4),
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
                "sentiment": "bullish" if hype_score >= 0.7 else "bearish" if hype_score <= 0.4 else "neutral",
                "metrics": {
                    "social_volume": social,
                    "hype_index": hype_score * 100,
                },
            },
            "contrarian": {
                "score": contrarian_score,
                "signal": "sell" if is_overvalued else "buy",
                "metrics": {"contrarian_index": contrarian_score * 100},
            },
        },
    }


class SimiVisionEngine:
    """
    Builds rich signal objects for the SimiVision Legendary Edition UI.

    Integrates with MindmapBridge for conviction decay and outcome-gated
    recommendations.
    """

    def __init__(
        self,
        registry_path: str = REGISTRY_PATH,
        soul_map_path: str = SOUL_MAP_PATH,
    ):
        self.registry_path = registry_path
        self.soul_map_path = soul_map_path
        self.bridge = MindmapBridge(
            persistence_path=soul_map_path, registry_path=registry_path
        )
        self.judge = AdversarialJudge(
            persistence_path=soul_map_path, registry_path=registry_path
        )

    def build_signals(self) -> List[Dict[str, Any]]:
        """Build signal objects for all subnets in the registry."""
        registry = _load_json(self.registry_path)
        decisions = _load_selector_decisions()
        decisions_by_id = {d["subnet_id"]: d for d in decisions if "subnet_id" in d}

        signals = []
        for key, item in registry.items():
            netuid = item.get("id", int(key))
            decision = decisions_by_id.get(netuid)

            signal = {
                "netuid": netuid,
                "name": item.get("name", f"Subnet {netuid}"),
                "status": item.get("status", "unknown"),
                "emission": item.get("emission"),
                "social_mentions": item.get("social_mentions"),
                "is_overvalued": item.get("is_overvalued", False),
                "consensus_score": decision.get("consensus_score") if decision else None,
                "recommended_action": decision.get("recommended_action") if decision else "hold",
                "rationale": self._build_rationale(netuid, item, decision),
            }
            signals.append(signal)

        return signals

    def _build_rationale(
        self,
        netuid: int,
        item: Dict[str, Any],
        decision: Optional[Dict[str, Any]],
    ) -> str:
        """Build a human-readable rationale for a subnet signal."""
        if decision is None:
            return f"No council consensus yet for {item.get('name', f'Subnet {netuid}')}."
        action = decision.get("recommended_action", "hold")
        score = decision.get("consensus_score", 0.0)
        return (
            f"Council consensus: {action} (score: {score:.2f}) "
            f"for {item.get('name', f'Subnet {netuid}')}."
        )

    def safe_snapshot(self, n: int = 3) -> Dict[str, Any]:
        """
        Build a safe SimiVision snapshot with top-N picks.

        Never raises — returns an empty/fallback structure on error.
        """
        try:
            registry = _load_json(self.registry_path)
            decisions = _load_selector_decisions()
            recommendations = self.bridge.get_brain_recommendations()

            # Build choices inline to avoid circular imports.
            result = self._build_choices(registry, decisions, recommendations)
            result["meta"]["freshness"] = {
                "checked_at": _now_iso(),
                "source": "simivision-engine",
            }
            return result
        except Exception as e:
            return {
                "date": datetime.now().strftime("%Y-%m-%d"),
                "choices": [],
                "alignment_score": None,
                "alignment_status": None,
                "meta": {
                    "source": "error",
                    "fallback_used": False,
                    "selector_decisions": 0,
                    "brain_recommendations": 0,
                    "error": str(e),
                    "freshness": {"checked_at": _now_iso()},
                },
            }

    def _build_choices(
        self,
        registry: Dict[str, Any],
        decisions: List[Dict[str, Any]],
        recommendations: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Build top-3 SimiVision decision cards."""
        recs = recommendations.get("recommendations", {}) if recommendations else {}

        meta = {
            "source": None,
            "fallback_used": False,
            "selector_decisions": 0,
            "brain_recommendations": 0,
            "error": None,
        }

        chosen_ids = set()
        ranked = []

        # Tier 1: selector decisions sorted by consensus score.
        selector_decisions = sorted(
            [d for d in (decisions or []) if d.get("subnet_id") is not None],
            key=lambda d: d.get("consensus_score", 0.0) or 0.0,
            reverse=True,
        )
        for d in selector_decisions[:3]:
            chosen_ids.add(d["subnet_id"])
            ranked.append(d)
        meta["selector_decisions"] = len(selector_decisions)

        # Tier 2: back-fill from Brain recommendations.
        if len(ranked) < 3 and recs:
            brain_candidates = []
            for sid, rec in recs.items():
                try:
                    subnet_id = int(sid)
                except (ValueError, TypeError):
                    continue
                if subnet_id in chosen_ids:
                    continue
                action = rec.get("action", "hold")
                target_weight = rec.get("target_weight", 0.5)
                direction = 1.0 if action == "accumulate" else -1.0 if action == "reduce" else 0.0
                score = target_weight * (1.0 if direction != 0 else 0.5)
                brain_candidates.append((score, subnet_id, action, target_weight))
            brain_candidates.sort(reverse=True)
            for _, subnet_id, action, target_weight in brain_candidates[: 3 - len(ranked)]:
                chosen_ids.add(subnet_id)
                item = registry.get(str(subnet_id), {}) if registry else {}
                ranked.append({
                    "subnet_id": subnet_id,
                    "consensus_score": 0.0,
                    "recommended_action": action,
                    "expert_breakdown": self._synthetic_breakdown(item),
                    "from_brain": True,
                    "brain_action": action,
                    "target_weight": target_weight,
                })
            meta["brain_recommendations"] = len(recs)
            if len(selector_decisions) < 3:
                meta["fallback_used"] = True

        # Tier 3: back-fill from registry highlights.
        if len(ranked) < 3 and registry:
            for field in ["emission", "social_mentions"]:
                if len(ranked) >= 3:
                    break
                items = sorted(
                    registry.items(),
                    key=lambda kv: kv[1].get(field, 0.0) or 0.0,
                    reverse=True,
                )
                for sid, item in items:
                    subnet_id = item.get("id", int(sid))
                    if subnet_id in chosen_ids:
                        continue
                    chosen_ids.add(subnet_id)
                    ranked.append({
                        "subnet_id": subnet_id,
                        "consensus_score": 0.0,
                        "recommended_action": "hold",
                        "expert_breakdown": self._synthetic_breakdown(item),
                        "from_registry": True,
                        "registry_highlight": field,
                    })
                    if len(ranked) >= 3:
                        break
            meta["fallback_used"] = True

        if not ranked:
            meta["source"] = "empty"
        elif meta["selector_decisions"] >= 3:
            meta["source"] = "selector"
        elif meta["selector_decisions"] > 0:
            meta["source"] = "selector+brain" if meta["brain_recommendations"] else "selector+registry"
        elif meta["brain_recommendations"]:
            meta["source"] = "brain"
        else:
            meta["source"] = "registry"

        choices = []
        for decision in ranked[:3]:
            feedback_boost = 0.0
            try:
                feedback_boost = self.bridge.get_simivision_feedback_boost(decision["subnet_id"])
            except Exception:
                pass
            choice = self._build_choice(registry, recs, decision, feedback_boost)
            choices.append(choice)

        # Log picks for change detection.
        if choices:
            pick_signature = [
                {"subnet_id": c["subnet_id"], "action": c["action"]} for c in choices
            ]
            try:
                self.bridge.log_simivision_picks(pick_signature)
            except Exception:
                pass

        return {
            "date": datetime.now().strftime("%Y-%m-%d"),
            "choices": choices,
            "alignment_score": None,
            "alignment_status": None,
            "meta": meta,
        }

    def _build_choice(
        self,
        registry: Dict[str, Any],
        recs: Dict[str, Any],
        decision: Dict[str, Any],
        feedback_boost: float = 0.0,
    ) -> Dict[str, Any]:
        """Build a single SimiVision choice from a decision-like object."""
        subnet_id = decision.get("subnet_id")
        item = registry.get(str(subnet_id), {}) if registry else {}
        name = item.get("name") or f"Subnet {subnet_id}"
        status = item.get("status", "unknown")
        action = decision.get("recommended_action", "hold")
        confidence = decision.get("consensus_score", 0.0) or 0.0
        breakdown = decision.get("expert_breakdown", {})
        brain_rec = recs.get(str(subnet_id), {}) if recs else {}
        brain_action = brain_rec.get("action")
        target_weight = brain_rec.get("target_weight", 0.5)

        direction = 1.0 if action == "accumulate" else -1.0 if action == "reduce" else 0.0
        edge_score = round(
            (confidence + feedback_boost) * target_weight * (1.0 if direction != 0 else 0.7),
            4,
        )
        edge_score = max(0.0, min(1.0, edge_score))

        apy = item.get("staking_data", {}).get("apy")
        preferred_entry = (
            f"Stake pool (~{apy * 100:.2f}% APY)" if apy
            else "Spot accumulation" if action == "accumulate"
            else "Hold position"
        )

        risk_flags = item.get("risk_flags", []) or []
        risk_penalty = len(risk_flags) + (1 if item.get("is_overvalued") else 0)
        reward = (apy or 0.0) * 100
        risk_score = max(1, risk_penalty)
        reward_risk_ratio = round(reward / risk_score, 2)
        if reward_risk_ratio >= 15:
            reward_risk_label = "High"
        elif reward_risk_ratio >= 5:
            reward_risk_label = "Medium"
        else:
            reward_risk_label = "Low"

        verdict = self.judge.judge_decision(
            {"recommended_action": action},
            {
                "emission": item.get("emission", 0.0),
                "social_mentions": item.get("social_mentions", 0),
                "status": status,
                "is_overvalued": item.get("is_overvalued", False),
            },
        )

        return {
            "subnet_id": subnet_id,
            "name": name,
            "status": status,
            "action": action,
            "confidence": confidence,
            "edge_score": edge_score,
            "preferred_entry": preferred_entry,
            "reward_risk": {
                "ratio": reward_risk_ratio,
                "label": reward_risk_label,
                "reward": round(reward, 2),
                "risk_penalty": risk_penalty,
            },
            "why_now": f"Council consensus: {action} (confidence: {confidence:.2f})",
            "invalidation": "Consensus shifts direction or confidence drops below 0.4.",
            "horizon": "1–3 days",
            "judge_agreement": "Agreed" if brain_action and action == brain_action else "No brain signal",
            "brain_action": brain_action,
            "target_weight": target_weight,
            "expert_breakdown": breakdown,
            "judge_verdict": verdict,
            "metrics": {
                "emission": item.get("emission"),
                "social_mentions": item.get("social_mentions"),
                "apy": apy,
                "total_stake": item.get("staking_data", {}).get("total_stake"),
                "is_overvalued": item.get("is_overvalued"),
                "risk_flags": risk_flags,
            },
            "protocol_tag": None,
            "feedback_boost": feedback_boost,
        }

    @staticmethod
    def _synthetic_breakdown(item: Dict[str, Any]) -> Dict[str, Any]:
        """Build a minimal traceable expert breakdown from registry metadata."""
        emission = item.get("emission", 0.0) or 0.0
        mentions = item.get("social_mentions", 0) or 0
        is_overvalued = item.get("is_overvalued", False)

        quant_score = 0.85 if emission > 1.0 else 0.4 if emission < 0.2 else 0.75
        hype_score = 0.9 if mentions > 1000 else 0.3 if mentions < 100 else 0.65
        contrarian_score = 0.2 if is_overvalued else 0.8

        return {
            "quant": {
                "score": quant_score,
                "metrics": {
                    "emission_stability": "high" if quant_score >= 0.7 else "low",
                    "performance_index": quant_score * 100,
                },
            },
            "hype": {
                "score": hype_score,
                "sentiment": "bullish" if hype_score >= 0.7 else "bearish" if hype_score <= 0.4 else "neutral",
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
        }