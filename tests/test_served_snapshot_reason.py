"""Why a seed is served must reach the label (MC act-on 7, #1484)."""

import json

from internal.council import score_snapshots as snaps
from tests.score_snapshot_testutil import complete_snapshot_payload


def _write(path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_seed_label_says_volume_missing(tmp_path):
    seed = tmp_path / "seed.json"
    _write(seed, complete_snapshot_payload())
    served = snaps.read_served_snapshot(path=str(tmp_path / "volume.json"), seed_path=str(seed))
    assert served.state is snaps.ServedState.SEED
    assert served.label()["reason"] == "volume_missing"


def test_seed_label_says_volume_not_complete(tmp_path):
    seed = tmp_path / "seed.json"
    volume = tmp_path / "volume.json"
    _write(seed, complete_snapshot_payload())
    _write(volume, {"day": [{"netuid": 2, "total_score": 1.0}], "hour": []})
    served = snaps.read_served_snapshot(path=str(volume), seed_path=str(seed))
    assert served.state is snaps.ServedState.SEED
    assert served.label()["reason"] == "volume_not_complete"


def test_volume_served_label_has_no_reason(tmp_path):
    volume = tmp_path / "volume.json"
    _write(volume, complete_snapshot_payload())
    served = snaps.read_served_snapshot(path=str(volume), seed_path=str(tmp_path / "none.json"))
    assert "reason" not in served.label()
