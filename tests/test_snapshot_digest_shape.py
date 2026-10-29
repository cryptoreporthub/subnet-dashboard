"""weights_digest and input_digest must be real digests, not just non-empty strings (#1484, review item 6)."""

from __future__ import annotations

import copy
import json

import pytest

from internal.council import score_snapshots as snaps
from tests.score_snapshot_testutil import complete_snapshot_payload, install_soul_map

WRONG_SHAPE = ["x", " ", "w" * 64, "A" * 64, "0" * 63, "0" * 65, "0" * 64 + "\n", 7, True, ["0" * 64], {"d": "0" * 64}]
WRONG_SHAPE_IDS = ["x", "blank", "not_hex", "upper_hex", "short", "long", "trailing_newline", "int", "bool", "list", "dict"]


def _snapshot(**provenance):
    snap = copy.deepcopy(complete_snapshot_payload())
    snap["provenance"].update(provenance)
    return snap


@pytest.fixture(autouse=True)
def _usable_soul_map(tmp_path, monkeypatch):
    install_soul_map(tmp_path, monkeypatch)


def test_untouched_fixture_is_complete():
    assert snaps.is_complete_snapshot(_snapshot()) is True


@pytest.mark.parametrize("key", ["weights_digest", "input_digest"])
@pytest.mark.parametrize("bad", WRONG_SHAPE, ids=WRONG_SHAPE_IDS)
def test_a_non_digest_value_is_not_a_complete_snapshot(key, bad):
    assert snaps.is_complete_snapshot(_snapshot(**{key: bad})) is False


@pytest.mark.parametrize("key", ["weights_digest", "input_digest"])
def test_a_well_formed_digest_of_any_value_still_passes_the_reader_check(key):
    # Readers (and the committed seed) cannot know the live weights; only the producer gate compares them.
    assert snaps.is_complete_snapshot(_snapshot(**{key: "0" * 64})) is True


def test_producer_gate_rejects_a_well_formed_digest_that_is_not_the_live_weights(tmp_path):
    wrong = _snapshot(weights_digest="0" * 64)
    wrong["written_at"] = wrong["build_started_at"] = snaps._now_iso()
    path = tmp_path / "score_snapshots.json"
    path.write_text(json.dumps(wrong))
    assert snaps.is_complete_snapshot(wrong) is True
    assert snaps.volume_has_fresh_complete_snapshot(str(path), max_age_seconds=0) is False
