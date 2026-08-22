"""Targeted tests for daily-pick latency logging (PR #1020).

Scope: the instrumentation must be timing-only. These tests pin:
1. effective_weights fallback import survives (no NameError on normal pick path).
2. _log_score_latency writes one JSONL row per subnet + never raises.
3. Tie-break behavior is unchanged (leader retained when no rule triggers).
"""

import json
import os
import tempfile

import internal.council.daily_pick as dp


def test_effective_weights_fallback_importable():
    # Regression: a prior draft removed this import while _weights_for_context still calls it.
    assert callable(dp.effective_weights)
    w = dp._weights_for_context({})
    assert set(w) == {"quant", "hype", "dark_horse", "technical"}


def test_log_score_latency_writes_jsonl_and_never_raises():
    rows = [
        {"ts": "2026-08-22T00:00:00Z", "run_id": "r1", "netuid": 4, "subnet": "Targon", "score_ms": 10.0, "outcome": "ok"},
        {"ts": "2026-08-22T00:00:01Z", "run_id": "r1", "netuid": 2, "subnet": "DSperse", "score_ms": 5.0, "outcome": "ok"},
    ]
    with tempfile.TemporaryDirectory() as tmp:
        old = dp.LATENCY_PATH
        dp.LATENCY_PATH = os.path.join(tmp, "lat.jsonl")
        try:
            dp._log_score_latency(rows, "r1")
            with open(dp.LATENCY_PATH) as f:
                lines = [json.loads(l) for l in f if l.strip()]
            assert len(lines) == 2
            assert {l["netuid"] for l in lines} == {4, 2}
            # best-effort: corrupt path must not raise
            dp.LATENCY_PATH = os.path.join(tmp, "nope", "x", "y.jsonl")
            dp._log_score_latency(rows, "r1")  # should warn, not raise
        finally:
            dp.LATENCY_PATH = old


def test_tie_break_leader_retained_when_no_rule_triggers():
    leader = {
        "subnet": {"netuid": 1, "name": "A", "price_change_24h": 0},
        "score": {"confidence": 0.5, "expert_contributions": {"quant": 0.1, "technical": 0.1}},
    }
    runner = {
        "subnet": {"netuid": 2, "name": "B", "price_change_24h": 0},
        "score": {"confidence": 0.5, "expert_contributions": {"quant": 0.1, "technical": 0.1}},
    }
    result = dp._apply_tie_break(leader, runner)
    # No rule triggered -> winner_changed must stay False (leader retained).
    assert result["winner_changed"] is False
