"""Graded accountability context for SimiVision chat."""

from internal.simivision.chat_service import build_simivision_prompt, call_llm
from internal.simivision.graded_context import (
    build_graded_context,
    build_offline_graded_reply,
    extract_netuids,
    format_graded_prompt_block,
    wants_trust_stats,
)


def test_graded_context_extracts_netuid():
    assert extract_netuids("Why SN64?") == [64]
    assert extract_netuids("Compare subnet 7 and subnet 9", cap=2) == [7, 9]
    assert extract_netuids("hello") == []


def test_prompt_includes_snippet_for_sn64(monkeypatch):
    monkeypatch.setattr(
        "internal.learning.predictions_store.load_predictions",
        lambda: {
            "predictions": [],
            "resolved": [
                {
                    "netuid": 64,
                    "correct": True,
                    "actual_pct": 3.1,
                    "horizon_type": "day",
                    "outcome": "hit",
                }
            ],
        },
    )
    graded = build_graded_context("Why SN64?", {}, include_pick_explain=False)
    prompt = build_simivision_prompt(
        "Why SN64?",
        {"simivision_picks": [], "source": "test", "expert_weights": {}, "graded": graded},
    )
    assert "GRADED ACCOUNTABILITY" in prompt
    assert "SN64 ledger" in prompt
    assert "Hit" in prompt


def test_prompt_includes_trust_for_accuracy_question(monkeypatch):
    monkeypatch.setattr(
        "internal.simivision.graded_context._load_trust_banner",
        lambda: {
            "headline": "Last 50 graded: 62% directionally right",
            "graded": 50,
            "ready": True,
        },
    )
    graded = build_graded_context("What is the council win rate?", {}, include_pick_explain=False)
    prompt = build_simivision_prompt(
        "What is the council win rate?",
        {"simivision_picks": [], "source": "test", "expert_weights": {}, "graded": graded},
    )
    assert "Council track record" in prompt
    assert "62%" in prompt


def test_generic_message_no_graded_bloat():
    graded = build_graded_context("hello", {})
    assert graded["active"] is False
    assert format_graded_prompt_block(graded) == ""


def test_offline_reply_uses_snippet_not_hallucination(monkeypatch):
    monkeypatch.setattr(
        "internal.learning.predictions_store.load_predictions",
        lambda: {
            "predictions": [],
            "resolved": [
                {
                    "netuid": 64,
                    "correct": False,
                    "actual_pct": -1.2,
                    "horizon_type": "day",
                    "outcome": "miss",
                }
            ],
        },
    )
    graded = build_graded_context("Tell me about SN64", {}, include_pick_explain=False)
    context = {"graded": graded, "source": "test"}
    reply = build_offline_graded_reply("Tell me about SN64", context)
    assert reply is not None
    assert "SN64" in reply
    assert "Miss" in reply
    assert "95%" not in reply


def test_call_llm_offline_prefers_graded_reply(monkeypatch):
    monkeypatch.delenv("CHUTES_API_KEY", raising=False)
    monkeypatch.delenv("THIRTY_SPOKES_API_KEY", raising=False)
    graded = {
        "active": True,
        "subnet_grades": {64: {"snippet": "Last call on this SN · Hit · vs 24h"}},
        "trust_banner": None,
    }
    reply, llm_used, provider = call_llm("prompt", "Why SN64?", {"graded": graded})
    assert llm_used is False
    assert provider == ""
    assert "SN64" in reply
    assert "Hit" in reply


def test_wants_trust_stats_keywords():
    assert wants_trust_stats("How accurate is the council?")
    assert not wants_trust_stats("hello there")


def test_build_graded_context_sources_for_subnet(monkeypatch):
    monkeypatch.setattr(
        "internal.learning.predictions_store.load_predictions",
        lambda: {"predictions": [], "resolved": []},
    )
    graded = build_graded_context("subnet 42 track record", {}, include_pick_explain=False)
    assert graded["active"] is True
    assert 42 in graded["subnet_grades"]
    assert any(s.get("id") == "sn42" for s in graded["sources"])
