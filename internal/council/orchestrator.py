"""
Orchestrator (The Syncer)

Coordinates state across the hierarchical, Mindmap-integrated Engine.
Responsible for calling the mindmap_bridge to read/write Soul-Map state,
and invoking the judge to compare predictions against actuals.
"""

import json
import os
from typing import Any, Dict, List, Optional
from internal.council.mindmap_bridge import MindmapBridge
from internal.council.selector import Selector
from internal.council.adversarial_judge import judge_decision

class Orchestrator:
    """
    Orchestrator (The Syncer)
    
    Coordinates state across the hierarchical, Mindmap-integrated Engine.
    Responsible for calling the mindmap_bridge to read/write Soul-Map state,
    and invoking the judge to compare predictions against actuals.
    """
    def __init__(self, mindmap_bridge: Optional[MindmapBridge] = None):
        self.mindmap_bridge = mindmap_bridge or MindmapBridge()
        self.selector = Selector(mindmap_bridge=self.mindmap_bridge)

    def run_daily_rotation(self, subnet_ids: Optional[List[int]] = None, context_map: Optional[Dict[int, Dict[str, Any]]] = None) -> Dict[str, Any]:
        """
        Runs the daily rotation process by invoking the Selector.

        Args:
            subnet_ids (list): List of subnet IDs to process.
            context_map (dict, optional): Context mapping for subnets.

        Returns:
            dict: The daily rotation results.
        """
        result = self.selector.process_daily_rotation(subnet_ids, context_map)
        decisions = result.get("daily_output", {}).get("decisions", [])

        # Loop through each decision and call judge_decision for each pick.
        verdicts = []
        for pick in decisions:
            verdict = judge_decision(pick)
            verdicts.append({
                "timestamp": verdict.get("timestamp", ""),
                "confidence": verdict.get("confidence", 0.5),
                "dissent": verdict.get("dissent", False),
                "reasoning": verdict.get("reasoning", ""),
            })

        # Persist verdicts into data/soul_map.json under key "verdicts".
        soul_map_path = os.path.join("data", "soul_map.json")
        soul_map = {}
        if os.path.exists(soul_map_path):
            try:
                with open(soul_map_path, "r") as f:
                    soul_map = json.load(f)
            except (json.JSONDecodeError, FileNotFoundError):
                soul_map = {}

        existing = soul_map.get("verdicts", [])
        if not isinstance(existing, list):
            existing = []
        existing.extend(verdicts)
        soul_map["verdicts"] = existing

        os.makedirs(os.path.dirname(soul_map_path), exist_ok=True)
        with open(soul_map_path, "w") as f:
            json.dump(soul_map, f, indent=2)

        return result