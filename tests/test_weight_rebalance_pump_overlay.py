"""Slice R rebalance + Slice M pump score overlay."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from internal.council.pump_overlay import apply_pump_score_overlay, pump_prior_0_1
from internal.council.signal_expert import expert_for_replay_row
from internal.council.state_vector import score_subnet_for_day
from internal.council.weights import (
    DEFAULT_WEIGHTS,
    merged_replay_rows,
    rebalance_council_weights,
    replay_weights_from_predictions,
    soft_blend_weights,
)


def test_expert_for_replay_uses_signal_type_not_stale_quant(tmp_path):
    row = {
        "expert": "quant",
        "signal_source": "council_day_pick",
        "signal_impact": {
            "impacts": [
                {"signal_type": "emission_change", "magnitude_pct": 2.0, "learned_weight": 1.0},
            ],
        },
        "correct": True,
    }
    assert expert_for_replay_row(row) == "quant"


def test_replay_skips_pump_lead(tmp_path):
    preds = tmp_path / "predictions.json"
    preds.write_text(
        json.dumps(
            {
                "predictions": [],
                "resolved": [
                    {
                        "pick_source": "pump_lead",
                        "expert": "hype",
                        "correct": True,
                        "outcome": "hit",
                        "resolved_at": "2026-01-01T00:00:00Z",
                    },
                    {
                        "expert": "technical",
                        "signal_source": "rsi_crossover",
                        "correct": True,
                        "outcome": "hit",
                        "resolved_at": "2026-01-02T00:00:00Z",
                    },
                ],
            }
        )
    )
    weights = replay_weights_from_predictions(str(preds))
    assert weights["technical"] == 1.02
    assert weights["hype"] == 1.0


def test_soft_blend_pulls_quant_off_ceiling():
    replayed = {**DEFAULT_WEIGHTS, "quant": 2.0, "hype": 0.9}
    blended = soft_blend_weights(replayed, replay_share=0.7)
    assert blended["quant"] < 2.0
    assert blended["quant"] > 1.0


def test_replay_includes_archive_when_current_epoch_thin(tmp_path, monkeypatch):
    preds = tmp_path / "predictions.json"
    archive_dir = tmp_path / "archive"
    archive_dir.mkdir()
    (archive_dir / "pre-epoch-2026-07-29").write_text(
        Path("tests/fixtures/acc1_archive_sample.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    monkeypatch.setattr("internal.council.weights.PREDICTIONS_ARCHIVE_DIR", str(archive_dir))
    preds.write_text(
        json.dumps(
            {
                "predictions": [],
                "resolved": [
                    {
                        "id": "current-1",
                        "expert": "technical",
                        "signal_source": "rsi_crossover",
                        "correct": True,
                        "outcome": "hit",
                        "resolved_at": "2026-07-30T00:00:00Z",
                    },
                ],
            }
        )
    )
    rows, meta = merged_replay_rows(str(preds), archive_dir=str(archive_dir))
    assert meta["current_graded"] == 1
    assert meta["archive_used"] is True
    assert len(rows) == 6

    weights = replay_weights_from_predictions(str(preds))
    assert weights["quant"] != 1.0
    assert weights["hype"] != 1.0


def test_rebalance_dry_run_does_not_require_soul_write(tmp_path, monkeypatch):
    soul = tmp_path / "soul_map.json"
    preds = tmp_path / "predictions.json"
    soul.write_text(
        json.dumps(
            {
                "adversarial_state": {
                    "council_weights": {"quant": 2.0, "hype": 0.9, "dark_horse": 0.95, "technical": 1.2}
                }
            }
        )
    )
    preds.write_text(
        json.dumps(
            {
                "predictions": [],
                "resolved": [
                    {
                        "expert": "technical",
                        "signal_source": "rsi_crossover",
                        "correct": False,
                        "outcome": "miss",
                        "resolved_at": "2026-01-01T00:00:00Z",
                    },
                ],
            }
        )
    )
    monkeypatch.setattr("internal.council.weights.SOUL_MAP_PATH", str(soul))
    result = rebalance_council_weights(
        predictions_path=str(preds),
        soul_map_path=str(soul),
        save=False,
    )
    assert result["ok"] is True
    assert result["before"]["quant"] == 2.0
    assert result["after"]["technical"] < 1.0
    stored = json.loads(soul.read_text())
    assert stored["adversarial_state"]["council_weights"]["quant"] == 2.0


def test_rebalance_reports_archive_usage(tmp_path, monkeypatch):
    soul = tmp_path / "soul_map.json"
    preds = tmp_path / "predictions.json"
    archive_dir = tmp_path / "archive"
    archive_dir.mkdir()
    (archive_dir / "pre-epoch-2026-07-29").write_text(
        Path("tests/fixtures/acc1_archive_sample.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    soul.write_text(json.dumps({"adversarial_state": {"council_weights": dict(DEFAULT_WEIGHTS)}}))
    preds.write_text(
        json.dumps(
            {
                "predictions": [],
                "resolved": [
                    {
                        "id": "current-1",
                        "expert": "technical",
                        "signal_source": "rsi_crossover",
                        "correct": True,
                        "resolved_at": "2026-07-30T00:00:00Z",
                    },
                ],
            }
        )
    )
    monkeypatch.setattr("internal.council.weights.SOUL_MAP_PATH", str(soul))
    monkeypatch.setattr("internal.council.weights.PREDICTIONS_ARCHIVE_DIR", str(archive_dir))
    result = rebalance_council_weights(
        predictions_path=str(preds),
        soul_map_path=str(soul),
        save=False,
    )
    assert result["archive_used"] is True
    assert result["rows_replayed"] >= 5
    assert result["after"]["quant"] != 1.0


def test_pump_prior_early_phase():
    prior = pump_prior_0_1({"phase": "ACCUMULATING", "composite_score": 0.5})
    assert prior is not None
    assert 0.5 < prior < 0.8


def test_pump_score_overlay_blends_total(monkeypatch):
    monkeypatch.setenv("PUMP_SCORE_OVERLAY_ALPHA", "0.10")
    sn = {
        "netuid": 28,
        "name": "gm",
        "price": 1.0,
        "price_change_24h": 3.0,
        "emission": 1.0,
        "apy": 15.0,
        "market_cap": 500_000,
    }
    entry = {"phase": "STIRRING", "composite_score": 0.55}
    with patch("internal.council.pump_overlay.pump_ladder_entry", return_value=entry):
        base = score_subnet_for_day(sn, market_context={"skip_pump_overlay": True})
        blended = score_subnet_for_day(sn)
    assert blended.get("pump_overlay") is not None
    assert blended["total_score"] != base["total_score"]
