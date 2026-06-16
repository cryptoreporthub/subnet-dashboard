"""
Adversarial Judge (The Feedback Loop)

Compares predictions against actual outcomes and updates the Mindmap
within the hierarchical, Mindmap-integrated Engine.
"""

class AdversarialJudge:
    def __init__(self):
        pass

    def judge_decision(self, decision, outcome):
        """
        Score a selector decision against observed outcome data.

        Returns a verdict dict with score, action, and a human-readable note.
        """
        action = decision.get("recommended_action", "hold") if decision else "hold"
        status = outcome.get("status", "unknown") if outcome else "unknown"
        emission = outcome.get("emission", 0.0) if outcome else 0.0
        social = outcome.get("social_mentions", 0) if outcome else 0
        is_overvalued = outcome.get("is_overvalued", False) if outcome else False

        if action == "accumulate":
            if status == "active" and emission >= 1.0 and social >= 100:
                score = 1.0
                note = "Accumulate supported by active status and strong emission/social signal."
            else:
                score = 0.5
                note = "Accumulate has weak support."
        elif action == "reduce":
            if is_overvalued:
                score = 1.0
                note = "Reduce supported by overvaluation flag."
            elif emission < 0.5 or social < 300:
                score = 0.5
                note = "Reduce has weak support."
            else:
                score = 0.5
                note = "Reduce has weak support."
        else:
            score = 0.5
            note = "Hold is a neutral verdict."

        return {"score": score, "action": action, "note": note}