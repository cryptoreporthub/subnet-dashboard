"""A legacy contrarian key is cleared from the two slots the write normalizes.

A legacy contrarian key is repaired once, when the weights are first imported into ledger.db.
The imported map has no such key, and later loads do not touch soul_map.json.
"""

from __future__ import annotations

import json

from internal.council import weights
from internal.store import ledger_db

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

    loaded = weights.load_weights(str(soul))
    with ledger_db.reader(str(soul)) as conn:
        stored = ledger_db.read_kind(conn, "expert")
    assert "contrarian" not in stored, "legacy key was imported into ledger.db"
    assert set(stored) == set(CANON)
    assert stored["dark_horse"] == 1.0
    soul_before = soul.read_bytes()

    ledger = tmp_path / "ledger.db"
    for _ in range(3):
        assert weights.load_weights(str(soul)) == loaded
    assert ledger.exists()
    assert soul.read_bytes() == soul_before, "later loads rewrote the soul map"


def test_non_dict_adversarial_state_does_not_crash_the_weight_write(tmp_path):
    """A malformed adversarial_state on disk must not crash a weight save."""
    soul = tmp_path / "soul_map.json"
    soul.write_text(json.dumps({"adversarial_state": ["not", "a", "dict"]}))
    original = json.loads(soul.read_text())
    assert weights.save_weights(dict(CANON), str(soul)) is True
    assert weights.load_weights(str(soul)) == CANON
    assert json.loads(soul.read_text()) == dict(original, weights_ledger_migrated={"ledger": "ledger.db"})
