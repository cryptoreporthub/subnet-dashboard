import pytest
from internal.council.orchestrator import Orchestrator


def test_judge_called_after_selector(monkeypatch):
    call_count = 0

    def mock_judge(pick):
        nonlocal call_count
        call_count += 1
        return {
            "timestamp": "2026-01-01T00:00:00",
            "confidence": 0.9,
            "dissent": False,
            "reasoning": "mock",
            "verdict": "aligned",
        }

    monkeypatch.setattr(
        "internal.council.orchestrator.judge_decision", mock_judge
    )

    orch = Orchestrator()
    decisions = orch.run_daily_rotation()

    assert call_count >= 1, (
        f"judge_decision should be called at least once, was called {call_count} times"
    )
    assert isinstance(decisions, dict)