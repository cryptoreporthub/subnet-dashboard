"""
Mindmap Bridge (The Connector)

Provides a read/write interface for the Soul-Map within the hierarchical,
Mindmap-integrated Engine.
"""

import os
import json
from typing import Any, Dict, Optional

from internal.file_utils import safe_write_json

class MindmapBridge:
    def __init__(self, persistence_path: str = "data/soul_map.json", registry_path: str = "config/registry.json"):
        self.persistence_path = persistence_path
        self.registry_path = registry_path
        self.soul_map_state: Dict[str, Any] = {}
        self.feedback_logs: list = []
        self._load_from_disk()

    def _load_from_disk(self):
        if os.path.exists(self.persistence_path):
            try:
                with open(self.persistence_path, "r") as f:
                    data = json.load(f)
                    self.soul_map_state = data.get("soul_map_state", {})
                    self.feedback_logs = data.get("feedback_logs", [])
            except Exception:
                self.soul_map_state = {}
                self.feedback_logs = []

    def _save_to_disk(self):
        dir_name = os.path.dirname(self.persistence_path)
        if dir_name and not os.path.exists(dir_name):
            os.makedirs(dir_name, exist_ok=True)
        try:
            # Merge into the full soul_map file so adversarial_state / expert
            # weights written by the learning loop are never clobbered.
            existing: Dict[str, Any] = {}
            if os.path.exists(self.persistence_path):
                with open(self.persistence_path, "r") as f:
                    loaded = json.load(f)
                    if isinstance(loaded, dict):
                        existing = loaded
            existing["soul_map_state"] = self.soul_map_state
            existing["feedback_logs"] = self.feedback_logs
            safe_write_json(self.persistence_path, existing)
        except Exception:
            pass

    def append_learning_trail(self, entry: Dict[str, Any]) -> None:
        """Append a mind-map learning trail row (pick/resolve/rotation events)."""
        trail = self.soul_map_state.setdefault("learning_trail", [])
        if not isinstance(trail, list):
            trail = []
            self.soul_map_state["learning_trail"] = trail
        trail.append(entry)
        if len(trail) > 200:
            self.soul_map_state["learning_trail"] = trail[-200:]
        self._save_to_disk()

    def get_brain_recommendations(self, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Retrieves the Brain's recommendations from the Mindmap.
        
        Args:
            context (dict, optional): Real context to enrich recommendations.
            
        Returns:
            dict: A dictionary of subnet IDs mapped to recommended actions/scores.
        """
        recommendations = {}
        if os.path.exists(self.registry_path):
            try:
                with open(self.registry_path, "r") as f:
                    registry = json.load(f)
                for sub_id, info in registry.items():
                    status = info.get("status", "active")
                    is_overvalued = info.get("is_overvalued", False)
                    emission = info.get("emission", 0.0)
                    social_mentions = info.get("social_mentions", 0)
                    
                    # If context has more up-to-date metrics, use them
                    if context:
                        # Try integer key first, then string key
                        sub_ctx = context.get(int(sub_id)) or context.get(str(sub_id))
                        if sub_ctx:
                            is_overvalued = sub_ctx.get("is_overvalued", is_overvalued)
                            emission = sub_ctx.get("emission", emission)
                            social_mentions = sub_ctx.get("social_mentions", social_mentions)
                    
                    if status == "deprecated" or is_overvalued:
                        action = "reduce"
                        target_weight = 0.1
                    elif emission > 1.5 and social_mentions > 1000:
                        action = "accumulate"
                        target_weight = 0.8
                    else:
                        action = "hold"
                        target_weight = 0.5
                        
                    recommendations[str(sub_id)] = {
                        "action": action,
                        "target_weight": target_weight,
                        "status": status,
                        "metrics": {
                            "emission": emission,
                            "social_mentions": social_mentions,
                            "is_overvalued": is_overvalued,
                            "emission_rank": info.get("emission_rank"),
                            "staking_data": info.get("staking_data")
                        }
                    }
            except Exception:
                pass
                
        # Fallback if registry is empty or failed to load
        if not recommendations:
            recommendations = {
                "1": {"action": "accumulate", "target_weight": 0.8},
                "2": {"action": "reduce", "target_weight": 0.2},
                "3": {"action": "hold", "target_weight": 0.5}
            }
            
        return {"recommendations": recommendations}

    def update_soul_map(self, selector_output: Dict[str, Any]) -> bool:
        """
        Updates the Soul-Map state with the Selector's daily output.
        
        Args:
            selector_output (dict): The daily output from the Selector.
            
        Returns:
            bool: True if the update was successful, False otherwise.
        """
        self.soul_map_state["last_selector_output"] = selector_output
        self.soul_map_state["updated_at"] = "2026-06-10T20:00:00Z"
        self._save_to_disk()
        return True

    def log_feedback(self, daily_output: Dict[str, Any], brain_recommendation: Dict[str, Any]) -> Dict[str, Any]:
        """
        Logs feedback comparing daily output against brain recommendations.
        
        Args:
            daily_output (dict): The Selector's daily output.
            brain_recommendation (dict): The Brain's recommendations.
            
        Returns:
            dict: The feedback loop analysis.
        """
        scores = []
        recommendations = brain_recommendation.get("recommendations", {})
        for decision in daily_output.get("decisions", []):
            sub_id = str(decision.get("subnet_id"))
            sel_action = decision.get("recommended_action")
            brain_rec = recommendations.get(sub_id)
            if brain_rec:
                brain_action = brain_rec.get("action")
                if sel_action == brain_action:
                    score = 1.0
                elif (sel_action == "hold" and brain_action in ("accumulate", "reduce")) or \
                     (brain_action == "hold" and sel_action in ("accumulate", "reduce")):
                    score = 0.5
                else:
                    score = 0.0
                scores.append(score)
            else:
                scores.append(0.5)
                
        alignment_score = sum(scores) / len(scores) if scores else 1.0
        alignment_score = round(alignment_score, 4)
        
        if alignment_score >= 0.75:
            status = "aligned"
        elif alignment_score >= 0.4:
            status = "partially_aligned"
        else:
            status = "divergent"
            
        feedback = {
            "daily_output": daily_output,
            "brain_recommendation": brain_recommendation,
            "alignment_score": alignment_score,
            "status": status
        }
        self.feedback_logs.append(feedback)
        self._save_to_disk()
        return feedback