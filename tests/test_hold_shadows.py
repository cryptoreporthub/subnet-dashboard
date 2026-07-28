"""Phase 3 — HOLD counterfactual shadows excluded from RF-2 / weight nudges."""

from __future__ import annotations

from internal.council.resolver import _compute_stats, _skip_council_learning
from internal.learning.predictions_store import update_stats


def test_shadow_skipped_for_council_learning():
    assert _skip_council_learning({"shadow": True}) is True
    assert _skip_council_learning({"counterfactual": True}) is True
    assert _skip_council_learning({"pick_source": "council"}) is False


def test_compute_stats_excludes_shadows():
    data = {
        "predictions": [{"netuid": 1, "shadow": True}],
        "resolved": [
            {"correct": True, "outcome": "correct", "netuid": 2},
            {"correct": False, "outcome": "wrong", "netuid": 3, "shadow": True},
            {"correct": True, "outcome": "correct", "netuid": 4, "shadow": True},
        ],
    }
    stats = _compute_stats(data)
    assert stats["correct"] == 1
    assert stats["wrong"] == 0
    assert stats["pending"] == 0  # shadow pending excluded


def test_update_stats_excludes_shadow_pending():
    data = {
        "predictions": [
            {"netuid": 1},
            {"netuid": 2, "shadow": True},
        ],
        "resolved": [
            {"correct": True},
            {"correct": False, "shadow": True},
        ],
    }
    update_stats(data)
    assert data["stats"]["pending"] == 1
    assert data["stats"]["correct"] == 1
    assert data["stats"]["wrong"] == 0


def test_hold_hero_option_a_still_present():
    from pathlib import Path

    html = Path("templates/partials/premium/council_stage.html").read_text(encoding="utf-8")
    assert "candidate" in html or "HOLD" in html
