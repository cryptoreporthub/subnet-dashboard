"""Mutation gate (#1479): each listed mutant must break a behaviour check."""

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


def test_m5_non_atomic_write_killed(tmp_path, monkeypatch):
    payload = complete_snapshot_payload(day_rows=[{"netuid": 1, "total_score": 1.0}])
    path = tmp_path / "atomic.json"

    def _naive(path_str: str, body: dict) -> None:
        with open(path_str, "w", encoding="utf-8") as handle:
            json.dump(body, handle)

    monkeypatch.setattr(snaps, "_atomic_write_json", _naive)
    snaps._atomic_write_json(str(path), payload)
    assert json.loads(path.read_text())["scorer_digest"]
    world = InvariantWorld(tmp_path, monkeypatch)
    world.start("complete_on_volume")

    def _crash_write(path_str: str, body: dict) -> None:
        with open(path_str + ".tmp", "w", encoding="utf-8") as handle:
            handle.write("{partial")
        raise OSError("non-atomic crash")

    monkeypatch.setattr(snaps, "_atomic_write_json", _crash_write)
    with pytest.raises((Failed, OSError)):
        snaps.save_score_snapshot(payload, world.volume_path)
        world.assert_invariant()


def test_m7_pending_top_picks_cached_killed(tmp_path, monkeypatch):
    import server

    payload = complete_snapshot_payload(day_rows=[{"netuid": 1, "total_score": 1.0}])
    monkeypatch.setattr(snaps, "SCORE_SNAPSHOTS_PATH", str(tmp_path / "v.json"))
    with open(snaps.SCORE_SNAPSHOTS_PATH, "w", encoding="utf-8") as handle:
        json.dump(payload, handle)
    server._TOP_PICKS_CACHE.update(
        payload={"hour_picks": [], "day_picks": [], "status": "pending_snapshot"},
        at=0,
    )
    monkeypatch.setattr(server, "_top_picks_cacheable", lambda _p: True)
    out = server._build_top_picks_cached()
    with pytest.raises(AssertionError):
        assert out.get("day_picks")


def test_m8_busy_returns_empty_killed(tmp_path, monkeypatch):
    import server

    payload = complete_snapshot_payload(day_rows=[{"netuid": 1, "total_score": 1.0}])
    monkeypatch.setattr(snaps, "SCORE_SNAPSHOTS_PATH", str(tmp_path / "v.json"))
    with open(snaps.SCORE_SNAPSHOTS_PATH, "w", encoding="utf-8") as handle:
        json.dump(payload, handle)

    def _empty_busy(_status):
        return {"hour_picks": [], "day_picks": [], "status": "busy"}

    monkeypatch.setattr(server, "_snapshot_only_top_picks", _empty_busy)
    out = server._snapshot_only_top_picks("busy")
    with pytest.raises(AssertionError):
        assert out.get("day_picks")
