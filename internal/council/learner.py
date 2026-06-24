import json
import os
import time
from datetime import datetime

class LearningLoop:
    def __init__(self, soul_map_path="data/soul_map.json", outcomes_path="data/outcomes.jsonl"):
        self.soul_map_path = soul_map_path
        self.outcomes_path = outcomes_path
        self._ensure_files()
        self.soul_map = self._load_json(soul_map_path)
        self.outcomes = self._load_jsonl(outcomes_path)

    def _ensure_files(self):
        os.makedirs(os.path.dirname(self.soul_map_path), exist_ok=True)
        if not os.path.exists(self.soul_map_path):
            with open(self.soul_map_path, 'w') as f:
                json.dump({"verdicts": [], "expert_weights": {}}, f)
        if not os.path.exists(self.outcomes_path):
            open(self.outcomes_path, 'w').close()

    def _load_json(self, path):
        try:
            with open(path) as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            return {}

    def _load_jsonl(self, path):
        outcomes = []
        if os.path.exists(path):
            with open(path) as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            outcomes.append(json.loads(line))
                        except json.JSONDecodeError:
                            pass
        return outcomes

    def run(self):
        # Import here to avoid circular imports at module level
        from internal.council.orchestrator import Orchestrator
        from internal.council.adversarial_judge import judge_decision
        
        orch = Orchestrator()
        result = orch.run_daily_rotation()
        decisions = result.get("daily_output", {}).get("decisions", [])
        
        for d in decisions:
            verdict = judge_decision(d)
            entry = {
                "netuid": d.get("netuid"),
                "timestamp": datetime.utcnow().isoformat(),
                "decision": d.get("action", "hold"),
                "consensus_score": d.get("consensus_score", 0),
                "brain_recommendation": d.get("brain_recommendation", ""),
                "verdict": verdict.get("verdict", "neutral"),
                "verdict_confidence": verdict.get("confidence", 0.5)
            }
            self._append_outcome(entry)

        if len(self.outcomes) >= 2:
            self._compare_outcomes()

        self.soul_map["last_run"] = datetime.utcnow().isoformat()
        self._save_soul_map()

        return {
            "last_run": self.soul_map.get("last_run"),
            "total_verdicts": len(self.soul_map.get("verdicts", [])),
            "total_outcomes": len(self.outcomes),
            "expert_weights": self.soul_map.get("expert_weights", {}),
            "aligned_pct": self._compute_aligned_pct(),
            "divergent_pct": self._compute_divergent_pct()
        }

    def _append_outcome(self, entry):
        with open(self.outcomes_path, 'a') as f:
            f.write(json.dumps(entry) + '\n')
        self.outcomes.append(entry)
        # outcomes.jsonl is the canonical outcome log

    def _compare_outcomes(self):
        # Compare past predictions to current signal direction
        # Boost/penalize expert weights based on alignment
        weights = self.soul_map.get("expert_weights")
        if not weights:
            weights = {
                "QuantExpert": 1.0, "HypeExpert": 1.0,
                "ContrarianExpert": 1.0, "TechnicalExpert": 1.0
            }
        
        # Simple heuristic: if recent outcomes had high consensus but diverged,
        # reduce weight on the dominant expert
        recent = self.outcomes[-5:] if len(self.outcomes) >= 5 else self.outcomes
        aligned = sum(1 for o in recent if o.get("verdict") == "aligned")
        divergent = sum(1 for o in recent if o.get("verdict") == "divergent")
        
        if divergent > aligned:
            # Penalize equally across experts when signals diverge
            for k in weights:
                weights[k] = max(0.5, weights[k] - 0.05)
        elif aligned > divergent:
            for k in weights:
                weights[k] = min(2.0, weights[k] + 0.02)
        
        self.soul_map["expert_weights"] = weights
        self._save_soul_map()

    def _save_soul_map(self):
        with open(self.soul_map_path, 'w') as f:
            json.dump(self.soul_map, f, indent=2)

    def _compute_aligned_pct(self):
        if not self.outcomes:
            return 0.0
        aligned = sum(1 for o in self.outcomes if o.get("verdict") == "aligned")
        return round(aligned / len(self.outcomes) * 100, 1)

    def _compute_divergent_pct(self):
        if not self.outcomes:
            return 0.0
        divergent = sum(1 for o in self.outcomes if o.get("verdict") == "divergent")
        return round(divergent / len(self.outcomes) * 100, 1)