"""A served seed is not the volume (#1484 round 3: metrics gauges and snapshot_age_seconds).

* `subnet_score_snapshot_age_seconds` is documented as the age of the served snapshot (volume or
  seed, -1 when none); it read -1 whenever the volume file was absent, even with a seed served.
* The coverage gauges describe the last producer build on this volume; a seed's coverage block
  was published as if it were live coverage.
* `snapshot_age_seconds()` is the volume's freshness; it returned the seed's age while the
  volume held something incomplete.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from internal.council import score_snapshots as snaps
from internal.metrics import (
    SCORE_SNAPSHOT_AGE_SECONDS,
    SCORE_SNAPSHOT_AGE_UNAVAILABLE,
    SCORE_SNAPSHOT_COVERAGE_COMPLETE,
    SCORE_SNAPSHOT_COVERAGE_PUBLISHED,
    SCORE_SNAPSHOT_SERVED_STATE,
    refresh_from_state,
)
from tests.score_snapshot_testutil import complete_snapshot_payload

pytestmark = pytest.mark.usefixtures("usable_soul_map")


def _iso(seconds_ago):
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)).isoformat().replace("+00:00", "Z")


def _write(path, *, seconds_ago, complete=True):
    snap = complete_snapshot_payload(day_rows=[{"netuid": 1, "total_score": 1.0}], written_at=_iso(seconds_ago))
    if not complete:
        snap["coverage"]["complete"] = False
    path.write_text(json.dumps(snap), encoding="utf-8")


@pytest.fixture
def paths(tmp_path, monkeypatch):
    volume, seed = tmp_path / "score_snapshots.json", tmp_path / "seed.json"
    monkeypatch.setattr(snaps, "SCORE_SNAPSHOTS_PATH", str(volume))
    monkeypatch.setattr(snaps, "SCORE_SNAPSHOT_SEED_PATH", str(seed))
    monkeypatch.setenv("SCORE_SNAPSHOT_CYCLE_PATH", str(tmp_path / "cycle.json"))
    return volume, seed


def _state(name):
    return SCORE_SNAPSHOT_SERVED_STATE.labels(state=name)._value.get()


# --- metrics ---


def test_the_age_gauge_follows_the_served_seed_when_the_volume_is_absent(paths):
    volume, seed = paths
    _write(seed, seconds_ago=300)

    refresh_from_state()

    assert _state("seed") == 1.0
    assert 290 <= SCORE_SNAPSHOT_AGE_SECONDS._value.get() <= 400


def test_the_age_gauge_is_still_minus_one_when_nothing_is_served(paths):
    refresh_from_state()
    assert _state("none") == 1.0
    assert SCORE_SNAPSHOT_AGE_SECONDS._value.get() == SCORE_SNAPSHOT_AGE_UNAVAILABLE


@pytest.mark.parametrize("volume_state", ["absent", "partial"])
def test_a_fresh_seed_is_not_published_as_live_coverage(paths, volume_state):
    volume, seed = paths
    _write(volume, seconds_ago=60)
    refresh_from_state()
    assert SCORE_SNAPSHOT_COVERAGE_COMPLETE._value.get() == 1.0  # a green volume, as a baseline
    if volume_state == "absent":
        volume.unlink()
    else:
        _write(volume, seconds_ago=60, complete=False)
    _write(seed, seconds_ago=120)  # fresh, complete: servable

    refresh_from_state()

    assert _state("seed") == 1.0
    assert SCORE_SNAPSHOT_COVERAGE_COMPLETE._value.get() == 0.0
    assert SCORE_SNAPSHOT_COVERAGE_PUBLISHED._value.get() == 0.0


def test_a_fresh_volume_still_publishes_its_coverage_and_its_own_age(paths):
    volume, seed = paths
    _write(volume, seconds_ago=60)
    _write(seed, seconds_ago=5000)

    refresh_from_state()

    assert _state("fresh") == 1.0
    assert SCORE_SNAPSHOT_COVERAGE_COMPLETE._value.get() == 1.0
    assert 55 <= SCORE_SNAPSHOT_AGE_SECONDS._value.get() <= 160


# --- snapshot_age_seconds: the volume's freshness, never the seed's ---


def test_snapshot_age_is_none_when_the_volume_file_is_absent_even_with_a_seed(paths):
    volume, seed = paths
    _write(seed, seconds_ago=300)
    assert snaps.snapshot_age_seconds() is None


def test_snapshot_age_is_the_volumes_age_when_the_volume_is_incomplete_and_a_seed_serves(paths):
    volume, seed = paths
    _write(volume, seconds_ago=100, complete=False)
    _write(seed, seconds_ago=5000)
    assert 95 <= snaps.snapshot_age_seconds() <= 200


def test_snapshot_age_is_the_volumes_age_when_the_volume_is_complete(paths):
    volume, seed = paths
    _write(volume, seconds_ago=100)
    _write(seed, seconds_ago=5000)
    assert 95 <= snaps.snapshot_age_seconds() <= 200


def test_snapshot_age_is_none_for_an_unreadable_volume_file_and_never_the_seeds(paths):
    volume, seed = paths
    volume.write_text("{not json")
    _write(seed, seconds_ago=300)
    assert snaps.snapshot_age_seconds() is None
