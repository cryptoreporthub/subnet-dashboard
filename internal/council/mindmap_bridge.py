"""
Mindmap Bridge (The Connector)

Provides a read/write interface for the Soul-Map within the hierarchical,
Mindmap-integrated Engine.
"""

import os
import json
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from internal.store.soul_map_io import read_soul_map, write_soul_map

# Mirror CYCLE_HISTORY_MAX=10 / learning_trail[-200:] — memory-only heal; on-disk
# shrink is the compaction operation (Runbook v4), not this constant alone.
FEEDBACK_LOGS_MAX = 10


class MindmapBridge:
    def __init__(self, persistence_path: str = "data/soul_map.json", registry_path: str = "config/registry.json"):
        self.persistence_path = persistence_path
        self.registry_path = registry_path
        self.soul_map_state: Dict[str, Any] = {}
        self.feedback_logs: list = []
        self._load_from_disk()

    def _load_from_disk(self):
        try:
            data = read_soul_map(self.persistence_path)
            self.soul_map_state = data.get("soul_map_state", {})
            logs = data.get("feedback_logs", [])
            if isinstance(logs, list):
                self.feedback_logs = logs[-FEEDBACK_LOGS_MAX:]
            else:
                # Non-list payload: preserve as empty list in memory (safe); do not
                # rewrite disk here — compaction owns on-disk shape.
                self.feedback_logs = []
        except Exception:
            self.soul_map_state = {}
            self.feedback_logs = []

    def _save_to_disk(self):
        dir_name = os.path.dirname(self.persistence_path)
        if dir_name and not os.path.exists(dir_name):
            os.makedirs(dir_name, exist_ok=True)

        def _apply(blob: Dict[str, Any]) -> None:
            # This bridge's snapshot is stale. Keep the persisted ledger and trail rows that other
            # bridges wrote, and union this bridge's own ledger ids (replay guard).
            current = blob.get("soul_map_state")
            current_state = current if isinstance(current, dict) else {}
            current_ledger = current_state.get("resolved_prediction_ids")
            own_ledger = self.soul_map_state.get("resolved_prediction_ids")
            if isinstance(current_ledger, list) or isinstance(own_ledger, list):
                merged: list = list(current_ledger) if isinstance(current_ledger, list) else []
                for prediction_id in own_ledger if isinstance(own_ledger, list) else []:
                    if prediction_id not in merged:
                        merged.append(prediction_id)
                self.soul_map_state["resolved_prediction_ids"] = merged
            if "learning_trail" in current_state:
                self.soul_map_state["learning_trail"] = current_state["learning_trail"]
            else:
                self.soul_map_state.pop("learning_trail", None)
            blob["soul_map_state"] = self.soul_map_state
            blob["feedback_logs"] = self.feedback_logs

        try:
            write_soul_map(_apply, self.persistence_path)
        except Exception:
            return

    def append_learning_trail(self, entry: Dict[str, Any], *, resolved_prediction_id: Any = None) -> None:
        """Append a mind-map learning trail row (pick/resolve/rotation events).

        A resolved prediction id is also recorded in ``resolved_prediction_ids`` in the same save.
        That ledger is never truncated, so a replay still matches after the trail window moves on.
        """
        def _apply(blob: Dict[str, Any]) -> None:
            # Mutate the latest on-disk blob under the save lock, not this bridge's
            # snapshot, so another bridge's earlier append survives this save.
            state = blob.get("soul_map_state")
            if not isinstance(state, dict):
                state = {}
                blob["soul_map_state"] = state
            if resolved_prediction_id is not None:
                ledger = state.get("resolved_prediction_ids")
                if not isinstance(ledger, list):
                    ledger = []
                    state["resolved_prediction_ids"] = ledger
                if resolved_prediction_id not in ledger:
                    ledger.append(resolved_prediction_id)
            trail = state.get("learning_trail")
            if not isinstance(trail, list):
                trail = []
            trail.append(entry)
            state["learning_trail"] = trail[-200:]

        saved = write_soul_map(_apply, self.persistence_path)
        latest = saved.get("soul_map_state")
        if isinstance(latest, dict):
            self.soul_map_state = latest

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
                
        # Fallback: honest-empty — never invent SN1/2/3 theater (LB-10)
        if not recommendations:
            return {
                "recommendations": {},
                "data_available": False,
                "source": "registry_heuristic",
                "reason": "no_registry_recommendations",
            }

        return {
            "recommendations": recommendations,
            "data_available": True,
            "source": "registry_heuristic",
        }

    def update_soul_map(self, selector_output: Dict[str, Any]) -> bool:
        """
        Updates the Soul-Map state with the Selector's daily output.
        
        Args:
            selector_output (dict): The daily output from the Selector.
            
        Returns:
            bool: True if the update was successful, False otherwise.
        """
        self.soul_map_state["last_selector_output"] = selector_output
        self.soul_map_state["updated_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
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
        if len(self.feedback_logs) > FEEDBACK_LOGS_MAX:
            self.feedback_logs = self.feedback_logs[-FEEDBACK_LOGS_MAX:]
        self._save_to_disk()
        return feedback