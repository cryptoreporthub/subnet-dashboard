"""
Learning Engine for Subnet Dashboard
Tracks expert accuracy and updates weights based on prediction performance.
"""
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

LEARNING_CONFIG = {
    "learning_rate": 0.1,
    "decay_factor": 0.99,
    "min_weight": 0.1,
    "max_weight": 2.0,
    "performance_window_days": 30
}

class LearningEngine:
    """Manages the learning loop for expert council weights."""
    
    def __init__(self, soul_map_path: str = "data/soul_map.json"):
        self.soul_map_path = soul_map_path
        self.config = LEARNING_CONFIG.copy()
    
    def load_soul_map(self) -> Dict:
        """Load the current soul map state."""
        try:
            with open(self.soul_map_path, "r") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error loading soul map: {e}")
            return {"expert_weights": {}, "performance_history": {}}
    
    def save_soul_map(self, data: Dict) -> None:
        """Save the updated soul map state."""
        try:
            with open(self.soul_map_path, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving soul map: {e}")
    
    def record_feedback(self, subnet_id: int, recommendation: str, actual_performance: Dict) -> None:
        """Record the outcome of a prediction for learning."""
        soul_map = self.load_soul_map()
        
        if "performance_history" not in soul_map:
            soul_map["performance_history"] = {}
        
        key = str(subnet_id)
        if key not in soul_map["performance_history"]:
            soul_map["performance_history"][key] = []
        
        # Determine if prediction was correct
        correct = actual_performance.get("correct_prediction", False)
        actual_change = actual_performance.get("price_change_7d", 0)
        
        record = {
            "subnet_id": subnet_id,
            "recommendation": recommendation,
            "actual_change": actual_change,
            "correct": correct,
            "timestamp": datetime.now().isoformat()
        }
        
        soul_map["performance_history"][key].append(record)
        
        # Keep only recent history (last 30 days)
        cutoff = datetime.now() - timedelta(days=self.config["performance_window_days"])
        soul_map["performance_history"][key] = [
            r for r in soul_map["performance_history"][key]
            if datetime.fromisoformat(r["timestamp"]) > cutoff
        ]
        
        self.save_soul_map(soul_map)
        self.update_weights()
    
    def update_weights(self) -> Dict:
        """Update expert weights based on recent performance."""
        soul_map = self.load_soul_map()
        
        if "performance_history" not in soul_map:
            return {}
        
        # Calculate accuracy for each expert
        expert_names = ["alpha", "beta", "gamma"]
        new_weights = {}
        
        for expert in expert_names:
            accuracy = self._calculate_expert_accuracy(expert, soul_map["performance_history"])
            current_weight = soul_map.get("expert_weights", {}).get(expert, 1.0)
            
            # Apply learning rate and decay
            new_weight = current_weight + (accuracy - 0.5) * self.config["learning_rate"]
            new_weight = max(self.config["min_weight"], min(self.config["max_weight"], new_weight))
            
            new_weights[expert] = round(new_weight, 4)
        
        soul_map["expert_weights"] = new_weights
        soul_map["last_updated"] = datetime.now().isoformat()
        
        self.save_soul_map(soul_map)
        return new_weights
    
    def _calculate_expert_accuracy(self, expert: str, history: Dict) -> float:
        """Calculate accuracy for a specific expert."""
        total = 0
        correct = 0
        
        for subnet_key, records in history.items():
            for record in records:
                total += 1
                if record.get("correct", False):
                    correct += 1
        
        return correct / total if total > 0 else 0.5
    
    def get_stats(self) -> Dict:
        """Return current learning stats."""
        soul_map = self.load_soul_map()
        return {
            "expert_weights": soul_map.get("expert_weights", {}),
            "config": self.config,
            "last_updated": soul_map.get("last_updated"),
            "total_records": sum(len(v) for v in soul_map.get("performance_history", {}).values())
        }


def create_feedback_endpoint(server_module):
    """Add feedback endpoint to Flask app."""
    from flask import request, jsonify
    
    @server_module.route("/api/feedback", methods=["POST"])
    def record_feedback():
        data = request.get_json() or {}
        subnet_id = data.get("subnet_id")
        recommendation = data.get("recommendation")
        actual_performance = data.get("actual_performance", {})
        
        if not subnet_id or not recommendation:
            return jsonify({"error": "Missing subnet_id or recommendation"}), 400
        
        engine = LearningEngine()
        engine.record_feedback(subnet_id, recommendation, actual_performance)
        
        return jsonify({"status": "feedback recorded", "success": True})
    
    @server_module.route("/api/learning/stats")
    def learning_stats():
        engine = LearningEngine()
        return jsonify(engine.get_stats())