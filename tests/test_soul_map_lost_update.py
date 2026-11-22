"""A soul-map writer must not drop keys another writer stored after its read (Gemini #1599)."""

import json

import pytest

from internal.council import formula_versions, rotation_tokens
from internal.council import weights as council_weights
from internal.store import soul_map_io


@pytest.fixture
def primed_soul_map(tmp_path, monkeypatch):
    path = tmp_path / "soul_map.json"
    path.write_text(json.dumps({"judge_weights": {"oracle": 0.5}}), encoding="utf-8")
    monkeypatch.setattr(council_weights, "SOUL_MAP_PATH", str(path))
    # Prime the read cache with the pre-existing blob.
    council_weights._load_raw(str(path))
    # Another writer stores a sibling key directly on disk after the cache was filled.
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    on_disk["sibling_writer_key"] = {"kept": True}
    path.write_text(json.dumps(on_disk), encoding="utf-8")
    return path


def _sibling_survives(path) -> bool:
    return json.loads(path.read_text(encoding="utf-8")).get("sibling_writer_key") == {"kept": True}


def test_rotation_snapshot_mirror_keeps_sibling_key(primed_soul_map):
    rotation_tokens._mirror_rotation_snapshot_to_soul_map([{"token": "a"}])

    assert _sibling_survives(primed_soul_map)


def test_calibration_version_record_keeps_sibling_key(primed_soul_map):
    cert = {"passed": True, "proposed_accuracy": 0.6, "current_accuracy": 0.5}
    formula_versions.record_calibration_version(
        cert=cert,
        weights_before={"oracle": 0.5},
        weights_after={"oracle": 0.6},
        soul_map_path=str(primed_soul_map),
    )

    assert _sibling_survives(primed_soul_map)
