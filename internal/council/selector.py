"""
Daily Rotation Engine (The Selector)

Acts as the "Daily Rotation Engine" that interfaces between the Experts
(quant.py, hype.py, contrarian.py) and the Orchestrator (orchestrator.py).
Integrates the Mindmap feedback loop interface to track daily output
against the Brain's recommendations.
"""

from typing import Any, Dict, List, Optional
from internal.council.experts.quant import QuantExpert
from internal.council.experts.hype import HypeExpert
from internal.council.experts.contrarian import ContrarianExpert
from internal.council.mindmap_bridge import MindmapBridge

class Selector:
    """
    Daily Rotation Engine (The Selector)
    
    Coordinates expert opinions, structures decision payloads for the Orchestrator,
    and tracks daily output against the Brain's recommendations via the Mindmap feedback loop.
    """
    def __init__(self, mindmap_bridge: Optional[MindmapBridge] = None):
        self.quant_expert = QuantExpert()
        self.hype_expert = HypeExpert()
        self.contrarian_expert = ContrarianExpert()
        self.mindmap_bridge = mindmap_bridge or MindmapBridge()
        self.daily_output_history: List[Dict[str, Any]] = []

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
        
        return {
            "quant": quant_opinion,
            "hype": hype_opinion,
            "contrarian": contrarian_opinion
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
        quant_score = expert_opinions["quant"].get("score", 0.5)
        hype_score = expert_opinions["hype"].get("score", 0.5)
        contrarian_score = expert_opinions["contrarian"].get("score", 0.5)
        
        # Calculate a weighted consensus score
        # Quant: 40%, Hype: 30%, Contrarian: 30%
        consensus_score = (quant_score * 0.4) + (hype_score * 0.3) + (contrarian_score * 0.3)
        
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
                }
            }
        }

    def track_against_brain(self, daily_output: Dict[str, Any]) -> Dict[str, Any]:
        """
        Fetches the Brain's recommendations from the MindmapBridge, compares the Selector's
        daily output against them, and logs/tracks the feedback loop.
        
        Args:
            daily_output (dict): The Selector's daily output.
            
        Returns:
            dict: The feedback loop analysis.
        """
        brain_recommendations = self.mindmap_bridge.get_brain_recommendations()
        feedback = self.mindmap_bridge.log_feedback(daily_output, brain_recommendations)
        
        # Update the Soul-Map state with the daily output
        self.mindmap_bridge.update_soul_map(daily_output)
        
        return feedback

    def process_daily_rotation(self, subnet_ids: List[int], context_map: Optional[Dict[int, Dict[str, Any]]] = None) -> Dict[str, Any]:
        """
        The main entry point for the Daily Rotation Engine.
        Processes a list of subnets, aggregates expert opinions, structures the decision payload,
        tracks against the Brain's recommendations, and returns the final structured daily rotation output.
        
        Args:
            subnet_ids (list): List of subnet IDs to process.
            context_map (dict, optional): A mapping of subnet ID to its specific context dictionary.
            
        Returns:
            dict: The final structured daily rotation output.
        """
        context_map = context_map or {}
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
        feedback = self.track_against_brain(daily_output)
        
        final_output = {
            "daily_output": daily_output,
            "feedback_loop": feedback
        }
        
        self.daily_output_history.append(final_output)
        return final_output