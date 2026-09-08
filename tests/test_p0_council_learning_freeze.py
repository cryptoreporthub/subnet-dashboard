"""P0.0 — council learning freeze gates online weight mutation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from internal.council import weights as weights_mod
from internal.council.weights import (
    council_learning_frozen,
    load_weights,
    nudge_expert,
    nudge_signal_weight,
    save_weights,
)
from internal.learning.loop_health import build_learning_loop_health


@pytest.fixture()
def soul(tmp_path, monkeypatch):
    path = tmp_path / "soul_map.json"
    path.write_text(
        json.dumps(
            {
                "adversarial_state": {
                    "council_weights": {
                        "quant": 1.5,
                        "hype": 1.0,
                        "dark_horse": 1.0,
                        "technical": 1.0,
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(weights_mod, "SOUL_MAP_PATH", str(path))
    return path


def test_freeze_default_on(monkeypatch):
    monkeypatch.delenv("COUNCIL_LEARNING_FROZEN", raising=False)
    assert council_learning_frozen() is True


def test_freeze_env_unfreeze(monkeypatch):
    monkeypatch.setenv("COUNCIL_LEARNING_FROZEN", "0")
    assert council_learning_frozen() is False


def test_nudge_expert_blocked_when_frozen(soul, monkeypatch):
    monkeypatch.setenv("COUNCIL_LEARNING_FROZEN", "1")
    before = load_weights(str(soul))
    assert nudge_expert("quant", True, str(soul)) is None
    after = load_weights(str(soul))
    assert after == before


def test_nudge_signal_blocked_when_frozen(soul, monkeypatch):
    monkeypatch.setenv("COUNCIL_LEARNING_FROZEN", "1")
    before = json.loads(Path(soul).read_text(encoding="utf-8"))
    assert nudge_signal_weight("hour", "rsi_crossover", True, str(soul)) is None
    after = json.loads(Path(soul).read_text(encoding="utf-8"))
    assert after == before


def test_nudge_expert_works_when_unfrozen(soul, monkeypatch):
    monkeypatch.setenv("COUNCIL_LEARNING_FROZEN", "0")
    before = float(load_weights(str(soul))["quant"])
    after = nudge_expert("quant", True, str(soul))
    assert after is not None
    assert after > before


def test_health_reports_frozen(monkeypatch, tmp_path):
    monkeypatch.setenv("COUNCIL_LEARNING_FROZEN", "1")
    monkeypatch.setenv("INLINE_WORKER", "0")
    daily = tmp_path / "daily_picks.json"
    daily.write_text("[]", encoding="utf-8")
    preds = tmp_path / "predictions.json"
    preds.write_text(
        json.dumps({"predictions": [], "resolved": [], "stats": {"pending": 0}}),
        encoding="utf-8",
    )
    report = build_learning_loop_health(
        daily_picks_path=str(daily),
        predictions_path=str(preds),
        soul_path=str(tmp_path / "missing_soul.json"),
    )
    assert report["learning_frozen"] is True
    assert report["learning_label"] == "learning frozen (P0.0)"
