"""Formula version bump on calibration fire."""

import json
from datetime import datetime, timedelta, timezone

from internal.council.formula_versions import load_formula_versions, record_calibration_version


def _soul(tmp_path, *, current="1.2", history=None):
    soul = tmp_path / "soul_map.json"
    soul.write_text(
        json.dumps(
            {
                "adversarial_state": {
                    "council_weights": {"quant": 0.3, "hype": 0.25, "dark_horse": 0.2, "technical": 0.25},
                    "formula_versions": {"council_weights": {"current": current, "history": history or []}},
                }
            }
        )
    )
    return soul


def test_record_calibration_version_bumps_on_meaningful_beat(tmp_path, monkeypatch):
    soul = _soul(tmp_path)
    monkeypatch.chdir(tmp_path)

    cert = {"passed": True, "proposed_accuracy": 0.62, "current_accuracy": 0.55, "holdout_size": 50}
    before = {"quant": 0.3, "hype": 0.25, "dark_horse": 0.2, "technical": 0.25}
    after = {"quant": 0.28, "hype": 0.27, "dark_horse": 0.22, "technical": 0.23}

    entry = record_calibration_version(
        cert=cert,
        weights_before=before,
        weights_after=after,
        soul_map_path=str(soul),
    )

    assert entry["version"] == "1.3"
    assert entry["version_bumped"] is True
    assert "beat" in entry["story"].lower()
    assert load_formula_versions(str(soul))["council_weights"]["current"] == "1.3"


def test_small_improvement_does_not_bump_version(tmp_path, monkeypatch):
    soul = _soul(tmp_path)
    monkeypatch.chdir(tmp_path)

    cert = {"passed": True, "proposed_accuracy": 0.565, "current_accuracy": 0.55, "holdout_size": 50}
    entry = record_calibration_version(
        cert=cert,
        weights_before={"quant": 0.3, "hype": 0.25, "dark_horse": 0.2, "technical": 0.25},
        weights_after={"quant": 0.29, "hype": 0.26, "dark_horse": 0.21, "technical": 0.24},
        soul_map_path=str(soul),
    )

    assert entry["version"] == "1.2"
    assert entry["version_bumped"] is False
    assert "2 pts" in entry["story"] or "still on v1.2" in entry["story"].lower()


def test_cooldown_blocks_second_bump_within_fourteen_days(tmp_path, monkeypatch):
    recent = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat().replace("+00:00", "Z")
    history = [
        {
            "version": "1.3",
            "previous_version": "1.2",
            "version_bumped": True,
            "fired_at": recent,
            "beat_previous": True,
        }
    ]
    soul = _soul(tmp_path, current="1.3", history=history)
    monkeypatch.chdir(tmp_path)

    cert = {"passed": True, "proposed_accuracy": 0.68, "current_accuracy": 0.55, "holdout_size": 50}
    entry = record_calibration_version(
        cert=cert,
        weights_before={"quant": 0.3, "hype": 0.25, "dark_horse": 0.2, "technical": 0.25},
        weights_after={"quant": 0.28, "hype": 0.27, "dark_horse": 0.22, "technical": 0.23},
        soul_map_path=str(soul),
    )

    assert entry["version_bumped"] is False
    assert entry["bump_block_reason"] == "cooldown"


def test_holdout_too_small_blocks_bump(tmp_path, monkeypatch):
    soul = _soul(tmp_path)
    monkeypatch.chdir(tmp_path)

    cert = {"passed": True, "proposed_accuracy": 0.62, "current_accuracy": 0.55, "holdout_size": 25}
    entry = record_calibration_version(
        cert=cert,
        weights_before={"quant": 0.3, "hype": 0.25, "dark_horse": 0.2, "technical": 0.25},
        weights_after={"quant": 0.28, "hype": 0.27, "dark_horse": 0.22, "technical": 0.23},
        soul_map_path=str(soul),
    )

    assert entry["version"] == "1.2"
    assert entry["bump_block_reason"] == "holdout_too_small"
