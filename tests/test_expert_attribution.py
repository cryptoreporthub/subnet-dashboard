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


# --- Phase 2 expert attribution (Grok LOCK) ---


def test_resolve_expert_attribution_hot_signal_replay():
    from internal.council.expert_attribution import resolve_expert_attribution

    row = {
        "signal_impact": {
            "impacts": [{"signal_type": "hot", "magnitude_pct": 3.0, "learned_weight": 1.0}],
        }
    }
    expert, source = resolve_expert_attribution(row)
    assert expert == "hype"
    assert source == "replay"


def test_resolve_expert_attribution_legacy_gamma():
    from internal.council.expert_attribution import resolve_expert_attribution

    expert, source = resolve_expert_attribution({"expert": "gamma"})
    assert expert == "dark_horse"
    assert source == "existing"


def test_resolve_stamps_and_nudges_same_replay_expert(tmp_path, monkeypatch):
    import json

    from internal.council import resolver

    soul_path = str(tmp_path / "soul_map.json")
    (tmp_path / "soul_map.json").write_text(
        json.dumps(
            {
                "soul_map_state": {"learning_trail": []},
                "adversarial_state": {
                    "council_weights": {
                        "quant": 1.0,
                        "hype": 1.0,
                        "dark_horse": 1.0,
                        "technical": 1.0,
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(resolver, "PREDICTIONS_PATH", str(tmp_path / "predictions.json"))
    import internal.council.weights as weights_mod

    monkeypatch.setattr(weights_mod, "SOUL_MAP_PATH", soul_path)

    nudged = []

    def _capture(correct, expert):
        nudged.append((expert, correct))

    monkeypatch.setattr(resolver, "_nudge_weights", _capture)

    prediction = {
        "id": "replay-only",
        "netuid": 1,
        "direction": "up",
        "predicted_pct": 2.0,
        "reference_price": 10.0,
        "horizon_type": "hour",
        "signal_impact": {
            "impacts": [{"signal_type": "hot", "magnitude_pct": 4.0, "learned_weight": 1.0}],
        },
    }
    resolver.resolve_prediction(prediction, current_price=10.4)
    assert prediction["expert"] == "hype"
    assert prediction.get("expert_attribution_source") == "replay"
    assert nudged == [("hype", True)]


def test_backfill_expert_attribution_dry_run(tmp_path, monkeypatch):
    import json

    from internal.learning.expert_backfill import backfill_expert_attribution

    pred_path = tmp_path / "predictions.json"
    pred_path.write_text(
        json.dumps(
            {
                "predictions": [],
                "resolved": [
                    {
                        "id": "r1",
                        "correct": True,
                        "signal_impact": {
                            "impacts": [{"signal_type": "hot", "magnitude_pct": 2.0}],
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("internal.learning.predictions_store.PREDICTIONS_PATH", str(pred_path))

    result = backfill_expert_attribution(dry_run=True)
    assert result["dry_run"] is True
    assert result["would_update"] == 1
    assert result["updated"] == 0
    assert result["by_source"].get("replay") == 1

    data = json.loads(pred_path.read_text(encoding="utf-8"))
    assert "expert" not in data["resolved"][0]
