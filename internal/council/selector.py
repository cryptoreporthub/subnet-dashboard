"""
Daily Rotation Engine (The Selector)

Acts as the "Daily Rotation Engine" that interfaces between the Experts
(quant.py, hype.py, contrarian.py) and the Orchestrator (orchestrator.py).
Integrates the Mindmap feedback loop interface to track daily output
against the Brain's recommendations.
"""

import os
from typing import Any, Dict, List, Optional
from internal.council.experts.quant import QuantExpert
from internal.council.experts.hype import HypeExpert
from internal.council.experts.contrarian import ContrarianExpert
from internal.council.experts.technical import TechnicalExpert
from internal.council.mindmap_bridge import MindmapBridge
from internal.council.state_vector import (
    build_subnet_state_vector,
    format_top_pick,
    score_subnet_for_day,
    score_subnet_for_hour,
)

# Default weights: quant 0.3, hype 0.25, contrarian 0.2, technical 0.25
DEFAULT_WEIGHTS = {
    "quant": float(os.environ.get("SELECTOR_WEIGHT_QUANT", "0.3")),
    "hype": float(os.environ.get("SELECTOR_WEIGHT_HYPE", "0.25")),
    "contrarian": float(os.environ.get("SELECTOR_WEIGHT_CONTRARIAN", "0.2")),
    "technical": float(os.environ.get("SELECTOR_WEIGHT_TECHNICAL", "0.25")),
}


class Selector:
    """
    Daily Rotation Engine (The Selector)

    Coordinates expert opinions, structures decision payloads for the Orchestrator,
    and tracks daily output against the Brain's recommendations via the Mindmap feedback loop.
    """
    def __init__(self, mindmap_bridge: Optional[MindmapBridge] = None, weights: Optional[Dict[str, float]] = None):
        self.quant_expert = QuantExpert()
        self.hype_expert = HypeExpert()
        self.contrarian_expert = ContrarianExpert()
        self.technical_expert = TechnicalExpert()
        self.mindmap_bridge = mindmap_bridge or MindmapBridge()
        if weights is not None:
            self.weights = weights
        else:
            # Load adaptive weights from soul_map.json or fall back to defaults
            self.weights = self.mindmap_bridge.get_expert_weights() or DEFAULT_WEIGHTS.copy()
        self.daily_output_history: List[Dict[str, Any]] = []

    def get_top_picks(self, subnets: List[dict]) -> Dict[str, Optional[dict]]:
        """
        Return the top subnet pick for the hour and day horizons.

        Uses the modular state vector builder and scoring helpers so the
        selection logic is reusable outside of the HTTP layer.
        """
        if not subnets:
            return {"hour": None, "day": None}

        scored = []
        for sn in subnets:
            netuid = sn.get("netuid")
            if netuid is None:
                continue
            sv = build_subnet_state_vector(netuid, subnets)
            if sv is None:
                continue
            sv["_score_hour"] = score_subnet_for_hour(sv)
            sv["_score_day"] = score_subnet_for_day(sv)
            scored.append(sv)

        if not scored:
            return {"hour": None, "day": None}

        hour_pick = max(scored, key=lambda x: x["_score_hour"])
        day_pick = max(scored, key=lambda x: x["_score_day"])

        hour_pick["_score"] = hour_pick["_score_hour"]
        day_pick["_score"] = day_pick["_score_day"]

        return {
            "hour": format_top_pick(hour_pick, rank=1),
            "day": format_top_pick(day_pick, rank=1),
        }

    def get_expert_opinions(self, subnet_id: int, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Queries Quant, Hype, and Contrarian experts for their analysis on a given subnet.
        
        Args:
            subnet_id (int): The ID of the subnet to analyze.
            context (dict, optional): Additional context for analysis.
            
        Returns:
            dict: A dictionary containing opinions from all three experts.
        """
        quant_opinion = self.quant_expert.analyze(subnet_id, context)
        hype_opinion = self.hype_expert.analyze(subnet_id, context)
        contrarian_opinion = self.contrarian_expert.analyze(subnet_id, context)
        technical_opinion = self.technical_expert.analyze(subnet_id, context)

        return {
            "quant": quant_opinion,
            "hype": hype_opinion,
            "contrarian": contrarian_opinion,
            "technical": technical_opinion,
        }

    def structure_decision_payload(self, subnet_id: int, expert_opinions: Dict[str, Any]) -> Dict[str, Any]:
        """
        Aggregates and structures the expert opinions into a unified payload for the Orchestrator.
        
        Args:
            subnet_id (int): The ID of the subnet.
            expert_opinions (dict): The opinions from the experts.
            
        Returns:
            dict: Structured decision payload.
        """
        quant_score = expert_opinions.get("quant", {}).get("score", 0.5)
        hype_score = expert_opinions.get("hype", {}).get("score", 0.5)
        contrarian_score = expert_opinions.get("contrarian", {}).get("score", 0.5)
        technical_score = expert_opinions.get("technical", {}).get("score", 0.5)

        # Calculate a weighted consensus score using configurable weights.
        w = self.weights
        consensus_score = (
            quant_score * w.get("quant", 0.3)
            + hype_score * w.get("hype", 0.25)
            + contrarian_score * w.get("contrarian", 0.2)
            + technical_score * w.get("technical", 0.25)
        )

        # Determine recommended action based on consensus score
        if consensus_score >= 0.75:
            action = "accumulate"
        elif consensus_score <= 0.4:
            action = "reduce"
        else:
            action = "hold"

        return {
            "subnet_id": subnet_id,
            "consensus_score": round(consensus_score, 4),
            "recommended_action": action,
            "expert_breakdown": {
                "quant": {
                    "score": quant_score,
                    "metrics": expert_opinions["quant"].get("metrics", {})
                },
                "hype": {
                    "score": hype_score,
                    "sentiment": expert_opinions["hype"].get("sentiment", "neutral"),
                    "metrics": expert_opinions["hype"].get("metrics", {})
                },
                "contrarian": {
                    "score": contrarian_score,
                    "signal": expert_opinions["contrarian"].get("signal", "hold"),
                    "metrics": expert_opinions["contrarian"].get("metrics", {})
                },
                "technical": {
                    "score": technical_score,
                    "signal": expert_opinions.get("technical", {}).get("signal", "hold"),
                    "metrics": expert_opinions.get("technical", {}).get("metrics", {})
                }
            }
        }

    def track_against_brain(self, daily_output: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Fetches the Brain's recommendations from the MindmapBridge, compares the Selector's
        daily output against them, and logs/tracks the feedback loop.
        
        Args:
            daily_output (dict): The Selector's daily output.
            context (dict, optional): Real context to pass to the MindmapBridge.
            
        Returns:
            dict: The feedback loop analysis.
        """
        brain_recommendations = self.mindmap_bridge.get_brain_recommendations(context=context)
        feedback = self.mindmap_bridge.log_feedback(daily_output, brain_recommendations)
        
        # Update the Soul-Map state with the daily output
        self.mindmap_bridge.update_soul_map(daily_output)
        
        return feedback

    def process_daily_rotation(self, subnet_ids: Optional[List[int]] = None, context_map: Optional[Dict[int, Dict[str, Any]]] = None) -> Dict[str, Any]:
        """
        The main entry point for the Daily Rotation Engine.
        Processes a list of subnets, aggregates expert opinions, structures the decision payload,
        tracks against the Brain's recommendations, and returns the final structured daily rotation output.
        
        Args:
            subnet_ids (list, optional): List of subnet IDs to process. If None, reads from registry.json.
            context_map (dict, optional): A mapping of subnet ID to its specific context dictionary.
            
        Returns:
            dict: The final structured daily rotation output.
        """
        import json
        import os
        
        context_map = context_map or {}
        registry_path = getattr(self.mindmap_bridge, "registry_path", "config/registry.json")
        
        # Load registry to get actual subnet IDs and context if needed
        registry = {}
        if os.path.exists(registry_path):
            try:
                with open(registry_path, "r") as f:
                    registry = json.load(f)
            except Exception:
                pass
                
        if not subnet_ids:
            subnet_ids = [int(k) for k in registry.keys()]
            
        # Enrich context_map with real data from registry.json if not already present
        for sub_id in subnet_ids:
            if sub_id not in context_map:
                info = registry.get(str(sub_id))
                if info:
                    context_map[sub_id] = {
                        "emission": info.get("emission", 0.0),
                        "social_mentions": info.get("social_mentions", 0),
                        "is_overvalued": info.get("is_overvalued", False)
                    }
                    
        decisions = []
        for subnet_id in subnet_ids:
            context = context_map.get(subnet_id)
            opinions = self.get_expert_opinions(subnet_id, context)
            payload = self.structure_decision_payload(subnet_id, opinions)
            decisions.append(payload)
            
        daily_output = {
            "date": "2026-06-10",
            "decisions": decisions
        }
        
        # Track against the Brain's recommendations via the feedback loop
        feedback = self.track_against_brain(daily_output, context=context_map)
        
        final_output = {
            "daily_output": daily_output,
            "feedback_loop": feedback
        }
        
        self.daily_output_history.append(final_output)
        return final_output