"""A zero-byte soul map holds no data, so it must not block writers.

A non-empty corrupt file still fails closed: it is refused and quarantined, never
replaced with a default map.
"""

from __future__ import annotations

import glob
import json

from internal.store import soul_map_io


def _mutate(blob):
    blob["probe"] = 1


def test_zero_byte_soul_map_lets_a_write_apply(tmp_path):
    path = tmp_path / "soul_map.json"
    path.write_bytes(b"")

    result = soul_map_io.write_soul_map(_mutate, path=str(path))

    assert result.outcome is soul_map_io.WriteOutcome.APPLIED, result.outcome
    assert json.loads(path.read_text())["probe"] == 1
    assert glob.glob(str(path) + "*.corrupt-*") == []


def test_non_empty_corrupt_soul_map_is_still_refused_and_quarantined(tmp_path):
    path = tmp_path / "soul_map.json"
    path.write_text("{truncated")

    result = soul_map_io.write_soul_map(_mutate, path=str(path))

    assert result.outcome is soul_map_io.WriteOutcome.UNREADABLE_BLOB, result.outcome
    assert glob.glob(str(path) + "*.corrupt-*"), "corrupt file was not quarantined"
