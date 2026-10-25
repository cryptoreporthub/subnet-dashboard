"""PR-B: complete-only publish, seed fallback, never-blank readers (#1479)."""

from __future__ import annotations

import json
import os

import pytest

from internal.council import score_snapshots as snaps
from internal.council.scorer_identity import SCORER_REVISION, current_scorer_digest, stamp_scorer_fields
from tests.score_snapshot_testutil import complete_snapshot_payload


@pytest.fixture(autouse=True)
def _paths(tmp_path, monkeypatch, request):
    if request.node.get_closest_marker("no_path_isolation"):
        return
    monkeypatch.setattr(snaps, "SCORE_SNAPSHOTS_PATH", str(tmp_path / "volume.json"))
    monkeypatch.setattr(snaps, "SCORE_SNAPSHOT_SEED_PATH", str(tmp_path / "seed.json"))
    monkeypatch.setenv("SCORE_SNAPSHOT_CYCLE_PATH", str(tmp_path / "cycle.json"))


@pytest.mark.no_path_isolation
def test_shipped_seed_is_a_complete_snapshot():
    from internal.council.seed_quality import validate_shipped_seed

    path = snaps.SCORE_SNAPSHOT_SEED_PATH
    if not os.path.isfile(path):
        pytest.skip("seed not generated in this checkout")
    with open(path, encoding="utf-8") as handle:
        payload = json.load(handle)
    assert snaps.is_complete_snapshot(payload)
    ok, reason = validate_shipped_seed(payload)
    assert ok, reason


@pytest.mark.no_path_isolation
def test_seed_is_outside_the_volume_mount_and_inside_the_image():
    default = os.environ.get(
        "SCORE_SNAPSHOT_SEED_PATH", os.path.join("data_seeds", "score_snapshots.json")
    )
    assert default.startswith("data_seeds")
    assert not default.startswith(os.path.join("data", ""))


def test_publish_refuses_an_incomplete_snapshot_and_leaves_the_served_file(tmp_path):
    good = complete_snapshot_payload(day_rows=[{"netuid": 1, "total_score": 1.0}])
    snaps.publish_complete_snapshot(good, snaps.SCORE_SNAPSHOTS_PATH)
    before = open(snaps.SCORE_SNAPSHOTS_PATH, "rb").read()
    bad = {"written_at": "2026-01-01T00:00:00Z", "day": [], "coverage": {"complete": False}}
    result = snaps.publish_complete_snapshot(bad, snaps.SCORE_SNAPSHOTS_PATH)
    assert result.get("published") is False
    assert result.get("refused") == "incomplete"
    assert open(snaps.SCORE_SNAPSHOTS_PATH, "rb").read() == before


def test_aged_complete_snapshot_is_served_labelled_not_blanked(tmp_path, monkeypatch):
    old = complete_snapshot_payload(
        day_rows=[{"netuid": 3, "total_score": 3.0}],
        written_at="2020-01-01T00:00:00Z",
    )
    with open(snaps.SCORE_SNAPSHOTS_PATH, "w", encoding="utf-8") as handle:
        json.dump(old, handle)
    monkeypatch.setattr(snaps, "SCORE_SNAPSHOT_MAX_AGE_SECONDS", 60)
    served = snaps.read_served_snapshot()
    assert served.servable
    assert served.state.value == "aged"
    picks = snaps.build_top_picks_from_snapshot([])
    assert picks and picks["day_picks"]


def test_zero_history_volume_serves_the_image_seed_until_first_complete_build(tmp_path):
    seed = complete_snapshot_payload(day_rows=[{"netuid": 7, "total_score": 7.0}])
    with open(snaps.SCORE_SNAPSHOT_SEED_PATH, "w", encoding="utf-8") as handle:
        json.dump(seed, handle)
    served = snaps.read_served_snapshot()
    assert served.state.value == "seed"
    picks = snaps.build_top_picks_from_snapshot(None)
    assert picks["day_picks"][0]["netuid"] == 7


def test_old_revision_volume_snapshot_falls_back_to_compatible_seed(tmp_path):
    seed = complete_snapshot_payload(day_rows=[{"netuid": 4, "total_score": 4.0}])
    with open(snaps.SCORE_SNAPSHOT_SEED_PATH, "w", encoding="utf-8") as handle:
        json.dump(seed, handle)
    stale = complete_snapshot_payload(day_rows=[{"netuid": 99, "total_score": 99.0}])
    stale["scorer_revision"] = SCORER_REVISION - 1
    with open(snaps.SCORE_SNAPSHOTS_PATH, "w", encoding="utf-8") as handle:
        json.dump(stale, handle)
    served = snaps.read_served_snapshot()
    assert served.state.value == "seed"
    assert served.snapshot["day"][0]["netuid"] == 4


def test_release_rejected_when_seed_scorer_incompatible(tmp_path):
    bad_seed = complete_snapshot_payload(day_rows=[{"netuid": 1, "total_score": 1.0}])
    bad_seed["scorer_digest"] = "deadbeef00000000"
    with open(snaps.SCORE_SNAPSHOT_SEED_PATH, "w", encoding="utf-8") as handle:
        json.dump(bad_seed, handle)
    assert not snaps.is_complete_snapshot(bad_seed)


def test_handler_timeout_serves_snapshot_picks(monkeypatch, tmp_path):
    from server import _snapshot_only_top_picks

    payload = complete_snapshot_payload(day_rows=[{"netuid": 8, "total_score": 8.0}])
    with open(snaps.SCORE_SNAPSHOTS_PATH, "w", encoding="utf-8") as handle:
        json.dump(payload, handle)
    out = _snapshot_only_top_picks("timeout")
    assert out["day_picks"]
    assert out["meta"]["fallback_status"] == "timeout"


def test_stamped_snapshots_carry_current_scorer_fields():
    payload = stamp_scorer_fields({"day": [{"netuid": 1, "total_score": 1.0}]})
    assert payload["scorer_revision"] == SCORER_REVISION
    assert payload["scorer_digest"] == current_scorer_digest()


def test_ci_seed_check_rejects_incompatible_seed(tmp_path):
    import subprocess
    import sys

    bad = complete_snapshot_payload(day_rows=[{"netuid": 1, "total_score": 1.0}])
    bad["scorer_digest"] = "deadbeef00000000"
    bad_path = tmp_path / "bad_seed.json"
    bad_path.write_text(json.dumps(bad), encoding="utf-8")
    env = {**os.environ, "SCORE_SNAPSHOT_SEED_PATH": str(bad_path)}
    proc = subprocess.run(
        [sys.executable, "scripts/check_score_snapshot_seed.py"],
        cwd=os.path.dirname(os.path.dirname(__file__)),
        env=env,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 2


from tests.score_snapshot_invariant_harness import (
    InvariantWorld,
    pair_cases,
    random_sequences,
)


@pytest.mark.parametrize("start,e1,e2", pair_cases(), ids=[f"{s}:{a}+{b}" for s, a, b in pair_cases()])
def test_every_pair_of_events_keeps_picks_complete_and_non_empty(tmp_path, monkeypatch, start, e1, e2):
    world = InvariantWorld(tmp_path, monkeypatch)
    world.start(start)
    world.assert_invariant()
    world.apply(e1)
    world.assert_invariant()
    world.apply(e2)
    world.assert_invariant()


@pytest.mark.parametrize("seq", random_sequences(), ids=[f"rand{i}" for i in range(25)])
def test_random_long_interleavings_keep_the_invariant(tmp_path, monkeypatch, seq):
    world = InvariantWorld(tmp_path, monkeypatch)
    world.start("complete_on_volume")
    world.assert_invariant()
    for event in seq:
        world.apply(event)
        world.assert_invariant()
