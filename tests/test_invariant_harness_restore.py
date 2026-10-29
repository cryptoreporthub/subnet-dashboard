"""The invariant harness must put back what an event stubs (#1484 round 3).

`capture_timeout` replaced `coverage_capture_deadline_seconds` and then "restored" it by reading the
attribute back after the stub was already installed, so the stub stayed in place for every later
event of the same sequence (a later `complete_build` ran against an already-expired capture deadline).
"""

from __future__ import annotations

import pytest

from internal.council import score_snapshots as snaps
from internal.council import snapshot_coverage as cov
from tests.score_snapshot_invariant_harness import InvariantWorld

pytestmark = pytest.mark.usefixtures("usable_soul_map")


def test_capture_timeout_puts_the_real_deadline_check_back(tmp_path, monkeypatch):
    original = cov.coverage_capture_deadline_seconds
    world = InvariantWorld(tmp_path, monkeypatch)
    world.start("first_boot_with_seed")

    world.apply("capture_timeout")

    assert cov.coverage_capture_deadline_seconds is original


def test_a_build_after_capture_timeout_runs_against_the_real_deadline(tmp_path, monkeypatch):
    world = InvariantWorld(tmp_path, monkeypatch)
    world.start("first_boot_with_seed")

    world.apply("capture_timeout")
    world.apply("complete_build")

    served = snaps.read_served_snapshot()
    assert served.origin == "volume"
    assert snaps.is_complete_snapshot(snaps.load_score_snapshot(world.volume_path))


def test_the_harness_restores_the_deadline_check_even_when_the_build_raises(tmp_path, monkeypatch):
    original = cov.coverage_capture_deadline_seconds
    world = InvariantWorld(tmp_path, monkeypatch)
    world.start("first_boot_with_seed")
    monkeypatch.setattr(snaps, "write_full_universe_snapshot", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))

    try:
        world.apply("capture_timeout")
    except RuntimeError:
        pass

    assert cov.coverage_capture_deadline_seconds is original
