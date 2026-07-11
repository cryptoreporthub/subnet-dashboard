"""Phase B — mindmap trail aggregator and panel summaries."""

from __future__ import annotations

import json

import pytest


def test_mindmap_trail_populated():
    from internal.learning.mindmap_aggregator import collect_trail_events, event_type_counts

    trail = collect_trail_events(limit=20)
    assert len(trail) >= 1
    counts = event_type_counts(trail)
    assert sum(counts.values()) >= 1


def test_mindmap_state_summaries(monkeypatch):
    from internal.learning import panel_summaries
    from internal.learning.mindmap_aggregator import build_mindmap_state

    monkeypatch.setattr(
        panel_summaries,
        "summarize_picks",
        lambda: {"text": "Picks ok.", "sentences": ["Picks ok.", "RedTeam wired."]},
    )
    state = build_mindmap_state()
    assert state.get("status") == "success"
    assert state.get("trail_count", 0) >= 1
    for key in ("council", "judges", "learning", "picks"):
        assert key in state.get("summaries", {})
        assert state["summaries"][key].get("sentences")


def test_learning_routes_mindmap_trail():
    from internal.learning.mindmap_aggregator import collect_trail_events

    trail = collect_trail_events(limit=5)
    payload = {
        "status": "success",
        "trail": trail,
        "count": len(trail),
    }
    assert payload["count"] >= 1


def test_normalize_expert_legacy():
    from internal.council import resolver

    assert resolver._normalize_expert({"expert": "gamma"}) == "dark_horse"


def test_alignment_nudge_updates_weight(tmp_path, monkeypatch):
    soul = tmp_path / "soul_map.json"
    soul.write_text(
        json.dumps(
            {
                "adversarial_state": {
                    "council_weights": {
                        "quant": 1.0,
                        "hype": 1.0,
                        "dark_horse": 1.0,
                        "technical": 1.0,
                    }
                },
                "soul_map_state": {"learning_trail": []},
            }
        ),
        encoding="utf-8",
    )
    import internal.council.weights as weights_mod

    monkeypatch.setattr(weights_mod, "SOUL_MAP_PATH", str(soul))

    from internal.learning.alignment_nudge import apply_alignment_nudge

    out = apply_alignment_nudge({"alignment_score": 0.9, "status": "aligned"})
    assert out.get("applied") is True
    updated = weights_mod.load_weights(str(soul))
    assert updated["quant"] > 1.0


def test_panel_summaries_live_council():
    from internal.learning.panel_summaries import summarize_council

    out = summarize_council()
    assert out.get("text")
    assert len(out.get("sentences") or []) >= 2
