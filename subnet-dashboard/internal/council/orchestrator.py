"""
Orchestrator (The Syncer)

Coordinates state across the hierarchical, Mindmap-integrated Engine.
Responsible for calling the mindmap_bridge to read/write Soul-Map state,
and invoking the judge to compare predictions against actuals.
"""

from typing import Any, Dict, List, Optional
from internal.council.mindmap_bridge import MindmapBridge
from internal.council.selector import Selector

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

    def run_daily_rotation(self, subnet_ids: List[int], context_map: Optional[Dict[int, Dict[str, Any]]] = None) -> Dict[str, Any]:
        """
        Runs the daily rotation process by invoking the Selector.
        
        Args:
            subnet_ids (list): List of subnet IDs to process.
            context_map (dict, optional): Context mapping for subnets.
            
        Returns:
            dict: The daily rotation results.
        """
        return self.selector.process_daily_rotation(subnet_ids, context_map)