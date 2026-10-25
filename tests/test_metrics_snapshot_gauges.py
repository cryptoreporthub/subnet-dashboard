"""Coverage gauges describe the volume snapshot only; a served seed must not read as live coverage."""

from __future__ import annotations

import json

import pytest

from internal import metrics
from internal.council import score_snapshots as snaps
from tests.score_snapshot_testutil import complete_snapshot_payload


@pytest.mark.parametrize("volume", ["missing", "incomplete"])
def test_seed_served_does_not_publish_live_coverage(tmp_path, monkeypatch, volume):
    seed = complete_snapshot_payload(day_rows=[{"netuid": 1, "total_score": 1.0}])
    seed["written_at"] = snaps._now_iso()
    (tmp_path / "seed.json").write_text(json.dumps(seed), encoding="utf-8")
    vol = tmp_path / "volume.json"
    if volume == "incomplete":
        vol.write_text(json.dumps({"day": [], "coverage": {"complete": False}}), encoding="utf-8")
    monkeypatch.setattr(snaps, "SCORE_SNAPSHOTS_PATH", str(vol))
    monkeypatch.setattr(snaps, "SCORE_SNAPSHOT_SEED_PATH", str(tmp_path / "seed.json"))
    monkeypatch.setenv("SCORE_SNAPSHOT_CYCLE_PATH", str(tmp_path / "cycle.json"))
    metrics.SCORE_SNAPSHOT_COVERAGE_COMPLETE.set(1.0)

    metrics._refresh_score_snapshot_gauges()

    assert metrics.SCORE_SNAPSHOT_COVERAGE_COMPLETE._value.get() == 0.0
