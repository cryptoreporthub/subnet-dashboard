"""Formula version bump on calibration fire."""

import json
import os

from internal.council.formula_versions import load_formula_versions, record_calibration_version


def test_record_calibration_version_bumps_and_story(tmp_path, monkeypatch):
    soul = tmp_path / "soul_map.json"
    soul.write_text(
        json.dumps(
            {
                "adversarial_state": {
                    "council_weights": {"quant": 0.3, "hype": 0.25, "dark_horse": 0.2, "technical": 0.25},
                    "formula_versions": {"council_weights": {"current": "1.2", "history": []}},
                }
            }
        )
    )
    monkeypatch.chdir(tmp_path)

    cert = {"passed": True, "proposed_accuracy": 0.62, "current_accuracy": 0.55}
    before = {"quant": 0.3, "hype": 0.25, "dark_horse": 0.2, "technical": 0.25}
    after = {"quant": 0.28, "hype": 0.27, "dark_horse": 0.22, "technical": 0.23}

    entry = record_calibration_version(
        cert=cert,
        weights_before=before,
        weights_after=after,
        soul_map_path=str(soul),
    )

    assert entry["version"] == "1.3"
    assert entry["previous_version"] == "1.2"
    assert entry["beat_previous"] is True
    assert "beat" in entry["story"].lower()

    versions = load_formula_versions(str(soul))
    assert versions["council_weights"]["current"] == "1.3"
    assert len(versions["council_weights"]["history"]) == 1
