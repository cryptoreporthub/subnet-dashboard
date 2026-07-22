"""Unclassified attribution — quant must not be the silent catch-all."""

from __future__ import annotations

from internal.council.resolver import _normalize_expert
from internal.council.state_vector import _expert_from_signal_source
from internal.council.weights import DEFAULT_WEIGHTS, _expert_hits_by_regime
from internal.learning.predictions_store import count_unclassified


def test_empty_and_unmatched_are_unclassified():
    assert _expert_from_signal_source(None) == "unclassified"
    assert _expert_from_signal_source("") == "unclassified"
    assert _expert_from_signal_source("neutral") == "unclassified"
    assert _expert_from_signal_source("council_day_pick") == "unclassified"
    assert _expert_from_signal_source("mystery_signal_v2") == "unclassified"


def test_keyword_buckets_still_map():
    assert _expert_from_signal_source("emission_momentum") == "quant"
    assert _expert_from_signal_source("emission_apy") == "unclassified"
    assert _expert_from_signal_source("apy_yield_spike") == "unclassified"
    assert _expert_from_signal_source("whale_accumulation") == "hype"
    assert _expert_from_signal_source("social_sentiment") == "hype"
    assert _expert_from_signal_source("delegation_flow") == "dark_horse"
    assert _expert_from_signal_source("rsi_crossover") == "technical"
    assert _expert_from_signal_source("macd_cross") == "technical"


def test_normalize_skips_unclassified_for_weight_nudges():
    assert _normalize_expert({"expert": "unclassified"}) is None
    assert _normalize_expert({"expert": "unknown"}) is None
    assert _normalize_expert({"expert": "neutral"}) is None
    assert _normalize_expert({"expert": "quant"}) == "quant"
    assert _normalize_expert({"signal_source": "fundamental_yield"}) == "quant"


def test_count_unclassified():
    data = {
        "predictions": [{"expert": "unclassified"}, {"expert": "quant"}],
        "resolved": [{"expert": "hype"}, {"expert": "unclassified"}, {"expert": "UNCLASSIFIED"}],
    }
    assert count_unclassified(data) == 3


def test_regime_hits_skip_unclassified(monkeypatch):
    rows = {
        "resolved": [
            {"expert": "quant", "correct": True, "outcome": "hit", "subnet_snapshot": {}},
            {"expert": "unclassified", "correct": True, "outcome": "hit", "subnet_snapshot": {}},
            {"expert": "hype", "correct": False, "outcome": "miss", "subnet_snapshot": {}},
            {"correct": True, "outcome": "hit", "subnet_snapshot": {}},  # missing expert
        ]
    }

    monkeypatch.setattr(
        "internal.learning.predictions_store.load_predictions",
        lambda: rows,
    )
    hits = _expert_hits_by_regime()
    chop = hits.get("chop", {})
    assert "unclassified" not in chop
    assert chop.get("quant") == [True]
    assert chop.get("hype") == [False]
    for name in chop:
        assert name in DEFAULT_WEIGHTS
