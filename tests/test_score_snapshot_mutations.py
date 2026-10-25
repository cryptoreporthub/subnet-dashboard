"""Invariant mutation killers (#1479) — library read path only."""

from __future__ import annotations

import json

import pytest
from _pytest.outcomes import Failed

from internal.council import score_snapshots as snaps
from tests.score_snapshot_invariant_harness import InvariantWorld
from tests.score_snapshot_testutil import complete_snapshot_payload


def test_m1_demotion_restored_killed(tmp_path, monkeypatch):
    world = InvariantWorld(tmp_path, monkeypatch)
    world.start("complete_on_volume")
    monkeypatch.setattr(snaps, "SCORE_SNAPSHOT_SEED_PATH", str(tmp_path / "no-seed.json"))
    with open(world.volume_path, "w", encoding="utf-8") as handle:
        json.dump({"coverage": {"complete": False}, "day": [{"netuid": 1, "total_score": 1.0}]}, handle)
    with pytest.raises((Failed, AssertionError)):
        world.assert_invariant()


def test_m2_age_7200_blank_killed(tmp_path, monkeypatch):
    world = InvariantWorld(tmp_path, monkeypatch)
    world.start("complete_on_volume")
    world.apply("age_past_alert")
    orig = snaps.read_served_snapshot

    def _blank_aged(**kwargs):
        served = orig(**kwargs)
        if served.state == snaps.ServedState.AGED:
            return snaps.ServedSnapshot(snaps.ServedState.NONE, None, None, None, "m2")
        return served

    monkeypatch.setattr(snaps, "read_served_snapshot", _blank_aged)
    with pytest.raises((Failed, AssertionError)):
        world.assert_invariant()


def test_m3_seed_ignored_killed(tmp_path, monkeypatch):
    world = InvariantWorld(tmp_path, monkeypatch)
    world.start("first_boot_with_seed")
    with open(world.volume_path, "w", encoding="utf-8") as handle:
        handle.write('{"coverage":{"complete":false},"day":[]}')
    monkeypatch.setattr(snaps, "SCORE_SNAPSHOT_SEED_PATH", str(tmp_path / "missing-seed.json"))
    with pytest.raises((Failed, AssertionError)):
        world.assert_invariant()


def test_m4_incompatible_scorer_accepted_killed(tmp_path, monkeypatch):
    world = InvariantWorld(tmp_path, monkeypatch)
    world.start("first_boot_with_seed")
    stale = complete_snapshot_payload(day_rows=[{"netuid": 99, "total_score": 99.0}])
    stale["scorer_revision"] = 0
    with open(world.volume_path, "w", encoding="utf-8") as handle:
        json.dump(stale, handle)
    assert snaps.read_served_snapshot().state.value == "seed"
    monkeypatch.setattr(snaps, "scorer_fields_match", lambda _snap: True)
    served = snaps.read_served_snapshot()
    with pytest.raises((Failed, AssertionError)):
        assert served.state.value == "seed"
        assert served.snapshot["day"][0]["netuid"] != 99


def test_m6_partial_served_killed(tmp_path, monkeypatch):
    world = InvariantWorld(tmp_path, monkeypatch)
    world.start("complete_on_volume")
    partial = {
        "coverage": {"complete": False},
        "day": [{"netuid": 1, "total_score": 1.0}],
        "hour": [],
    }

    def _serve_partial(**_kwargs):
        return snaps.ServedSnapshot(snaps.ServedState.FRESH, partial, 0.0, "volume", "m6")

    monkeypatch.setattr(snaps, "read_served_snapshot", _serve_partial)
    with pytest.raises((Failed, AssertionError)):
        world.assert_invariant()
