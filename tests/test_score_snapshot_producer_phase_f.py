"""Publish moves seed→fresh (#1484 act-on 2). Producer ownership: test_score_snapshot_producer_ownership.py."""

from __future__ import annotations

import json

import pytest

from internal.council import score_snapshots as snaps
from tests.score_snapshot_testutil import complete_snapshot_payload


def test_fresh_volume_publish_served_as_fresh_not_seed(tmp_path, monkeypatch):
    seed = complete_snapshot_payload(day_rows=[{"netuid": 1, "total_score": 1.0}])
    monkeypatch.setattr(snaps, "SCORE_SNAPSHOT_SEED_PATH", str(tmp_path / "seed.json"))
    (tmp_path / "seed.json").write_text(json.dumps(seed), encoding="utf-8")
    volume = tmp_path / "volume.json"
    monkeypatch.setattr(snaps, "SCORE_SNAPSHOTS_PATH", str(volume))
    assert snaps.read_served_snapshot().state.value == "seed"
    fresh = complete_snapshot_payload(
        day_rows=[{"netuid": 2, "total_score": 2.0}],
        written_at=snaps._now_iso(),
    )
    snaps.publish_complete_snapshot(fresh, str(volume))
    served = snaps.read_served_snapshot()
    assert served.state.value == "fresh"
    assert served.origin == "volume"
