import pytest
from internal.council.selector import Selector
from internal.council.orchestrator import Orchestrator
from internal.council.mindmap_bridge import MindmapBridge

def test_selector_initialization():
    selector = Selector()
    assert selector.quant_expert is not None
    assert selector.hype_expert is not None
    assert selector.contrarian_expert is not None
    assert selector.mindmap_bridge is not None
    assert len(selector.daily_output_history) == 0

def test_get_expert_opinions():
    selector = Selector()
    opinions = selector.get_expert_opinions(1, {"emission": 1.5, "social_mentions": 1200, "is_overvalued": False})
    
    assert opinions["quant"]["score"] == 0.85
    assert opinions["hype"]["score"] == 0.9
    assert opinions["contrarian"]["score"] == 0.8

def test_structure_decision_payload():
    selector = Selector()
    opinions = {
        "quant": {"score": 0.85, "metrics": {}},
        "hype": {"score": 0.9, "sentiment": "bullish", "metrics": {}},
        "contrarian": {"score": 0.8, "signal": "buy", "metrics": {}}
    }
    payload = selector.structure_decision_payload(1, opinions)
    
    assert payload["subnet_id"] == 1
    # Consensus score: (0.85 * 0.4) + (0.9 * 0.3) + (0.8 * 0.3) = 0.34 + 0.27 + 0.24 = 0.85
    assert payload["consensus_score"] == 0.85
    assert payload["recommended_action"] == "accumulate"

def test_process_daily_rotation():
    orchestrator = Orchestrator()
    subnet_ids = [1, 2]
    context_map = {
        1: {"emission": 1.5, "social_mentions": 1200, "is_overvalued": False},
        2: {"emission": 0.1, "social_mentions": 50, "is_overvalued": True}
    }
    
    result = orchestrator.run_daily_rotation(subnet_ids, context_map)
    
    assert "daily_output" in result
    assert "feedback_loop" in result
    
    daily_output = result["daily_output"]
    assert len(daily_output["decisions"]) == 2
    
    # Subnet 1 should be accumulate
    assert daily_output["decisions"][0]["subnet_id"] == 1
    assert daily_output["decisions"][0]["recommended_action"] == "accumulate"
    
    # Subnet 2 should be reduce
    assert daily_output["decisions"][1]["subnet_id"] == 2
    assert daily_output["decisions"][1]["recommended_action"] == "reduce"
    
    # Feedback loop check
    feedback = result["feedback_loop"]
    assert feedback["status"] == "aligned"
    assert feedback["alignment_score"] == 0.75