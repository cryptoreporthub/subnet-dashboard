"""A legacy contrarian key is cleared from the two slots the write normalizes.

A legacy contrarian key is repaired once, when the weights are first imported into ledger.db.
The imported map has no such key, and soul_map.json is left as it was.
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

    soul_before = soul.read_bytes()
    loaded = weights.load_weights(str(soul))
    assert "contrarian" not in loaded, "legacy key still in council weights"

    ledger = tmp_path / "ledger.db"
    for _ in range(3):
        assert weights.load_weights(str(soul)) == loaded
    assert ledger.exists()
    assert soul.read_bytes() == soul_before, "the import must leave soul_map.json as it found it"


def test_non_dict_adversarial_state_does_not_crash_the_weight_write(tmp_path):
    """A malformed adversarial_state on disk must not crash a weight save."""
    soul = tmp_path / "soul_map.json"
    soul.write_text(json.dumps({"adversarial_state": ["not", "a", "dict"]}))
    before = soul.read_bytes()
    assert weights.save_weights(dict(CANON), str(soul)) is True
    assert weights.load_weights(str(soul)) == CANON
    assert soul.read_bytes() == before
