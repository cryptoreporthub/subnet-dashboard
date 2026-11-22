"""A legacy contrarian key is cleared from the two slots the write normalizes.

Head returned early when the normalized maps matched, so a stale root or council key stayed on
disk. The fix rewrites those slots once; later loads must not rewrite the file. The
soul_map_state slot is not cleared by the write, as at base, so the ledger is still replayed on
each load. That is pre-existing behavior and is not asserted here.
"""

from __future__ import annotations

import json

from internal.council import weights

CANON = {"quant": 1.0, "hype": 1.0, "dark_horse": 1.0, "technical": 1.0}


def test_legacy_contrarian_is_cleared_and_later_loads_do_not_rewrite(tmp_path, monkeypatch):
    soul = tmp_path / "soul_map.json"
    stale = dict(CANON, contrarian=1.3)
    soul.write_text(json.dumps({
        "adversarial_state": {"council_weights": dict(stale)},
        "expert_weights": dict(stale),
        "soul_map_state": {"expert_weights": dict(stale)},
    }))
    (tmp_path / "predictions.json").write_text(
        json.dumps({"predictions": [], "resolved": [], "stats": {}})
    )
    monkeypatch.setattr(weights, "SOUL_MAP_PATH", str(soul))

    weights.load_weights(str(soul))
    stored = json.loads(soul.read_text())
    assert "contrarian" not in stored["adversarial_state"]["council_weights"], "legacy key still in council weights"
    assert "contrarian" not in stored["expert_weights"], "legacy key still in root expert weights"

    before = soul.read_bytes()
    for _ in range(3):
        weights.load_weights(str(soul))
    assert soul.read_bytes() == before, "later loads rewrote a repaired soul map"


def test_non_dict_adversarial_state_does_not_crash_the_weight_write(tmp_path):
    """A malformed adversarial_state on disk must not crash a weight save."""
    soul = tmp_path / "soul_map.json"
    soul.write_text(json.dumps({"adversarial_state": ["not", "a", "dict"]}))
    weights.save_weights(dict(CANON), str(soul))
    assert json.loads(soul.read_text())["adversarial_state"]["council_weights"]
