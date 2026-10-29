"""The producer gate (volume_has_fresh_complete_snapshot) reads provenance defensively (#1531 3a)."""

from __future__ import annotations

import json

import pytest

from internal.council import score_snapshots as snaps
from tests.score_snapshot_testutil import complete_snapshot_payload


def _volume(tmp_path, mutate):
    snap = complete_snapshot_payload(written_at=snaps._now_iso())
    mutate(snap)
    path = tmp_path / "score_snapshots.json"
    path.write_text(json.dumps(snap), encoding="utf-8")
    return str(path)


@pytest.mark.parametrize("junk", ["x", [1], 7, True, ["weights_digest"]])
def test_non_dict_provenance_is_not_fresh_and_does_not_raise(tmp_path, junk):
    path = _volume(tmp_path, lambda s: s.__setitem__("provenance", junk))
    assert snaps.volume_has_fresh_complete_snapshot(path=path) is False


def test_missing_weights_digest_is_not_fresh(tmp_path):
    path = _volume(tmp_path, lambda s: s["provenance"].pop("weights_digest"))
    assert snaps.volume_has_fresh_complete_snapshot(path=path) is False


def test_null_weights_digest_is_not_fresh(tmp_path):
    path = _volume(tmp_path, lambda s: s["provenance"].__setitem__("weights_digest", None))
    assert snaps.volume_has_fresh_complete_snapshot(path=path) is False


def _write_soul(path, quant):
    blob = {"adversarial_state": {"council_weights": {"quant": quant, "hype": 1.0, "dark_horse": 1.0, "technical": 1.0}}}
    path.write_text(json.dumps(blob))


@pytest.fixture
def soul_map(tmp_path, monkeypatch):
    path = tmp_path / "soul_map.json"
    _write_soul(path, 1.0)
    monkeypatch.setattr("internal.council.weights.SOUL_MAP_PATH", str(path))
    # The loader keeps a short in-process cache of file reads; an edit on disk must be seen at once here.
    monkeypatch.setattr("internal.store.soul_map_io._CACHE_TTL", 0)
    return path


def test_fixture_snapshot_is_fresh_only_while_its_digest_matches_the_live_soul_map(tmp_path, soul_map):
    path = _volume(tmp_path, lambda s: None)
    assert snaps.volume_has_fresh_complete_snapshot(path=path) is True
    _write_soul(soul_map, 1.7)
    assert snaps.volume_has_fresh_complete_snapshot(path=path) is False


def test_a_snapshot_stamped_with_a_foreign_weights_digest_is_not_fresh(tmp_path, soul_map):
    path = _volume(tmp_path, lambda s: s["provenance"].__setitem__("weights_digest", "0" * 64))
    assert snaps.volume_has_fresh_complete_snapshot(path=path) is False
