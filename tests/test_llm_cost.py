"""LLM cost rolling stats for SimiVision chat."""

import json

from internal.ops.llm_cost import build_llm_cost_report, record_chat_usage


def test_record_and_report(tmp_path, monkeypatch):
    path = tmp_path / "llm_cost.json"
    monkeypatch.setenv("LLM_COST_PATH", str(path))
    monkeypatch.setenv("LLM_COST_PER_M_INPUT", "1.0")
    monkeypatch.setenv("LLM_COST_PER_M_OUTPUT", "1.0")

    record_chat_usage(
        llm_used=True,
        model="deepseek-ai/DeepSeek-V3.2-TEE",
        provider="https://api.chutes.ai/v1",
        prompt_tokens=1000,
        completion_tokens=400,
        total_tokens=1400,
    )
    record_chat_usage(
        llm_used=False,
        model="local-fallback",
        provider="internal",
        status="no_api_key",
    )

    report = build_llm_cost_report()
    assert report["totals"]["calls"] == 2
    assert report["totals"]["llm_calls"] == 1
    assert report["totals"]["fallback_calls"] == 1
    assert report["totals"]["prompt_tokens"] == 1000
    assert report["totals"]["completion_tokens"] == 400
    assert report["totals"]["estimated_usd"] == 0.0014
    assert report["averages_per_llm_call"]["estimated_usd"] == 0.0014
    assert len(report["recent"]) == 2

    with open(path) as f:
        saved = json.load(f)
    assert saved["totals"]["llm_calls"] == 1
