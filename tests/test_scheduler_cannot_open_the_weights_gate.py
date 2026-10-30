"""A scheduler tick must not create, repair or rewrite the soul_map (#1484 round 3, item 2).

`_tick_body` used to record its cycle summary inside soul_map.json before building. With a missing
soul_map that created the file, and with a corrupt one it replaced it, so the weights gate then
digested default weights and passed. The summary now has its own file, and a soul_map is only
"usable" when it holds real council weights.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from internal.council import score_snapshots as snaps
from internal.council import weights
from internal.council.scorer_identity import _canonical_digest, current_weights_digest
from tests.score_snapshot_testutil import complete_snapshot_payload
from tests.test_snapshot_membership_provenance import _producer_env, _universe

REPO = Path(__file__).resolve().parents[1]

REAL_WEIGHTS = {"adversarial_state": {"council_weights": {"quant": 1.2, "hype": 0.9, "dark_horse": 1.0, "technical": 1.1}}}
UNRELATED_ONLY = {
    "prediction_resolver_scheduler": {"last_cycle": {"run_at": "2026-10-28T00:00:00Z", "ok": True}},
    "rotation_tokens_snapshot": {"tokens": []},
}


def _default_weights_digest():
    """What the gate would compute from a soul_map that holds nothing: the default weights."""
    missing = "/nonexistent/soul_map.json"
    return _canonical_digest({"council": weights.load_weights(missing), "signal": weights.load_signal_weights(missing)})


def _stage(tmp_path, monkeypatch, kind):
    """Real producer over a fixed universe; a volume snapshot stamped with the default-weights digest."""
    volume, soul, scored = _producer_env(tmp_path, monkeypatch, _universe([1, 2, 3]))
    soul = Path(soul)
    if kind == "missing":
        soul.unlink()
    elif kind == "corrupt":
        soul.write_text("{not json")
    elif kind == "unrelated_only":
        soul.write_text(json.dumps(UNRELATED_ONLY))
    elif kind == "weights_in_other_slot_non_numeric":
        soul.write_text(json.dumps({"adversarial_state": {"council_weights": {"quant": "high", "hype": None}}}))
    snap = complete_snapshot_payload()
    snap["provenance"]["weights_digest"] = _default_weights_digest()
    volume.write_text(json.dumps(snap))
    monkeypatch.setattr(snaps, "SCORE_SNAPSHOT_SEED_PATH", str(REPO / "data_seeds" / "score_snapshots.json"))
    from internal.store import soul_map_io

    soul_map_io._cache.clear()
    return volume, soul, scored


def _tick():
    return snaps.ScoreSnapshotScheduler()._tick_body(reschedule=False)


@pytest.mark.parametrize("kind", ["missing", "corrupt", "unrelated_only", "weights_in_other_slot_non_numeric"])
def test_a_tick_leaves_an_unusable_soul_map_exactly_as_it_found_it(tmp_path, monkeypatch, kind):
    volume, soul, scored = _stage(tmp_path, monkeypatch, kind)
    before = soul.read_bytes() if soul.exists() else None

    result = _tick()

    after = soul.read_bytes() if soul.exists() else None
    assert after == before  # not created, not repaired, not rewritten (byte for byte)
    assert result["skipped"] == "weights_unavailable"
    assert scored == []


@pytest.mark.parametrize("kind", ["missing", "corrupt", "unrelated_only", "weights_in_other_slot_non_numeric"])
def test_after_a_tick_the_gate_is_still_not_fresh_and_the_seed_is_still_served(tmp_path, monkeypatch, kind):
    volume, soul, _ = _stage(tmp_path, monkeypatch, kind)
    assert snaps.volume_has_fresh_complete_snapshot(str(volume), max_age_seconds=0) is False

    _tick()

    assert current_weights_digest() is None
    assert snaps.volume_has_fresh_complete_snapshot(str(volume), max_age_seconds=0) is False
    served = snaps.read_served_snapshot(path=str(tmp_path / "no_volume.json"))
    assert served.servable is True
    assert served.origin == "seed"


def test_a_tick_does_not_touch_a_usable_soul_map_either(tmp_path, monkeypatch):
    volume, soul, _ = _stage(tmp_path, monkeypatch, "usable")
    soul.write_text(json.dumps(REAL_WEIGHTS))
    before = soul.read_bytes()

    _tick()

    assert soul.read_bytes() == before
    assert "score_snapshot_scheduler" not in json.loads(soul.read_text())


def test_the_cycle_summary_has_its_own_file_beside_the_soul_map(tmp_path, monkeypatch):
    volume, soul, _ = _stage(tmp_path, monkeypatch, "missing")

    _tick()

    state = tmp_path / "soul" / "score_snapshot_scheduler.json"
    last = json.loads(state.read_text())["last_cycle"]
    assert last["skipped"] == "weights_unavailable"
    assert last["phase"] is None  # the final summary replaced the in-flight "scoring" one


# --- "usable" means real council weights ---


@pytest.mark.parametrize(
    "blob",
    [
        UNRELATED_ONLY,
        {"adversarial_state": {}},
        {"adversarial_state": {"council_weights": {}}},
        {"adversarial_state": {"council_weights": {"quant": "high", "hype": None, "unknown_expert": 1.0}}},
        {"adversarial_state": {"council_weights": {"quant": True}}},
        {"adversarial_state": {"council_weights": {"quant": float("nan")}}},
        {"adversarial_state": {"council_weights": [1, 2]}},
        {"expert_weights": {}},
        {"soul_map_state": {"expert_weights": {"nope": 1.0}}},
        {"adversarial_state": {"signal_weights": {"day": {"rsi_crossover": 1.5}}}},
    ],
    ids=lambda b: json.dumps(b, default=str)[:60],
)
def test_a_soul_map_without_real_council_weights_has_no_digest(tmp_path, blob):
    path = tmp_path / "soul_map.json"
    path.write_text(json.dumps(blob))
    assert current_weights_digest(str(path)) is None


@pytest.mark.parametrize(
    "blob",
    [
        REAL_WEIGHTS,
        {"expert_weights": {"quant": 1.0}},
        {"soul_map_state": {"expert_weights": {"darkhorse": 0.8}}},
        {"adversarial_state": {"council_weights": {"contrarian": 1.1}}},
    ],
)
def test_each_stored_form_of_the_council_weights_counts(tmp_path, blob):
    path = tmp_path / "soul_map.json"
    path.write_text(json.dumps(blob))
    assert isinstance(current_weights_digest(str(path)), str)


# --- readers of the cycle summary keep working ---


def test_the_in_flight_marker_is_read_from_the_new_file(tmp_path, monkeypatch):
    from internal.council.scheduler_cycle_state import write_last_cycle

    soul = tmp_path / "soul_map.json"
    soul.write_text("{}")
    monkeypatch.setattr(weights, "SOUL_MAP_PATH", str(soul))
    write_last_cycle({"run_at": snaps._now_iso(), "ok": False, "phase": "scoring"})
    assert snaps.ScoreSnapshotScheduler()._scoring_in_progress() is True
    write_last_cycle({"run_at": snaps._now_iso(), "ok": True, "phase": None})
    assert snaps.ScoreSnapshotScheduler()._scoring_in_progress() is False


def test_a_legacy_in_flight_marker_is_still_read_until_the_new_file_exists(tmp_path, monkeypatch):
    from internal.council.scheduler_cycle_state import write_last_cycle

    soul = tmp_path / "soul_map.json"
    soul.write_text(json.dumps({"score_snapshot_scheduler": {"last_cycle": {"run_at": snaps._now_iso(), "phase": "scoring"}}}))
    monkeypatch.setattr(weights, "SOUL_MAP_PATH", str(soul))
    from internal.store import soul_map_io

    soul_map_io._cache.clear()
    assert snaps.ScoreSnapshotScheduler()._scoring_in_progress() is True
    write_last_cycle({"run_at": snaps._now_iso(), "ok": True, "phase": None})  # the new file wins over the old key
    assert snaps.ScoreSnapshotScheduler()._scoring_in_progress() is False


def test_loop_health_reads_the_new_file_and_falls_back_to_the_legacy_key(tmp_path, monkeypatch):
    from internal.council.scheduler_cycle_state import write_last_cycle
    from internal.learning.loop_health import _score_snapshot_meta

    soul = tmp_path / "soul_map.json"
    soul.write_text(json.dumps({"score_snapshot_scheduler": {"last_cycle": {"run_at": "2026-01-01T00:00:00Z", "ok": True}}}))
    from internal.store import soul_map_io

    soul_map_io._cache.clear()
    snap = str(tmp_path / "no_snapshots.json")
    assert _score_snapshot_meta(snap, soul_path=str(soul))["last_cycle"]["run_at"] == "2026-01-01T00:00:00Z"
    monkeypatch.setattr(weights, "SOUL_MAP_PATH", str(soul))
    write_last_cycle({"run_at": "2026-10-28T01:00:00Z", "ok": True})
    assert _score_snapshot_meta(snap, soul_path=str(soul))["last_cycle"]["run_at"] == "2026-10-28T01:00:00Z"


def test_a_corrupt_cycle_file_is_read_as_absent_and_never_raises(tmp_path, monkeypatch):
    from internal.council.scheduler_cycle_state import (
        read_last_cycle,
        read_last_cycle_with_status,
        scheduler_state_path,
    )

    soul = tmp_path / "soul_map.json"
    soul.write_text("{}")
    monkeypatch.setattr(weights, "SOUL_MAP_PATH", str(soul))
    Path(scheduler_state_path()).write_text("{not json")
    assert read_last_cycle() == {}
    assert read_last_cycle_with_status() == ({}, "unreadable")


def test_non_utf8_bytes_in_new_cycle_state_file_are_unreadable(tmp_path, monkeypatch):
    from internal.council import scheduler_cycle_state as scs
    from internal.council.scheduler_cycle_state import (
        read_last_cycle_with_status,
        scheduler_state_path,
    )

    soul = tmp_path / "soul_map.json"
    soul.write_text("{}")
    monkeypatch.setattr(weights, "SOUL_MAP_PATH", str(soul))
    Path(scheduler_state_path()).write_bytes(b"\xff\xfe not-valid-utf8")
    new, unreadable = scs._read_new(str(soul))
    assert new is None and unreadable is True
    assert read_last_cycle_with_status() == ({}, "unreadable")


def test_mutation_non_utf8_must_not_be_treated_as_missing(tmp_path, monkeypatch):
    from internal.council import scheduler_cycle_state as scs

    soul = tmp_path / "soul_map.json"
    soul.write_text("{}")
    monkeypatch.setattr(weights, "SOUL_MAP_PATH", str(soul))
    Path(scs.scheduler_state_path()).write_bytes(b"\xff\xfe")

    real_read_new = scs._read_new

    def _unreadable_is_missing(soul_map_path=None):
        new, unreadable = real_read_new(soul_map_path)
        if unreadable:
            return None, False
        return new, unreadable

    monkeypatch.setattr(scs, "_read_new", _unreadable_is_missing)
    assert scs.read_last_cycle_with_status() == ({}, "missing")


def test_non_utf8_new_cycle_file_with_legacy_read_last_cycle_returns_legacy(tmp_path, monkeypatch):
    from internal.council.scheduler_cycle_state import (
        read_last_cycle,
        read_last_cycle_with_status,
        scheduler_state_path,
    )

    legacy_cycle = {
        "run_at": "2026-01-01T00:00:00Z",
        "ok": True,
        "phase": "scoring",
        "progress": "2/128",
    }
    soul = tmp_path / "soul_map.json"
    soul.write_text(json.dumps({"score_snapshot_scheduler": {"last_cycle": legacy_cycle}}))
    monkeypatch.setattr(weights, "SOUL_MAP_PATH", str(soul))
    Path(scheduler_state_path()).write_bytes(b"\xff\xfe")
    assert read_last_cycle() == legacy_cycle
    assert read_last_cycle_with_status() == (legacy_cycle, "unreadable")


def test_mutation_non_utf8_legacy_fallback_requires_unreadable_flag(tmp_path, monkeypatch):
    from internal.council import scheduler_cycle_state as scs

    legacy_cycle = {"run_at": "2026-01-01T00:00:00Z", "ok": True}
    soul = tmp_path / "soul_map.json"
    soul.write_text(json.dumps({"score_snapshot_scheduler": {"last_cycle": legacy_cycle}}))
    monkeypatch.setattr(weights, "SOUL_MAP_PATH", str(soul))
    Path(scs.scheduler_state_path()).write_bytes(b"\xff\xfe")

    def _broken_read(soul_map_path=None):
        new, unreadable = scs._read_new(soul_map_path)
        if unreadable:
            return {}
        if new is not None:
            return dict(new)
        return scs._read_legacy(soul_map_path)

    monkeypatch.setattr(scs, "read_last_cycle", _broken_read)
    assert scs.read_last_cycle() == {}


def test_unreadable_legacy_soul_map_with_active_tick_is_probe_unknown(
    tmp_path, monkeypatch
):
    from internal.council.scheduler_cycle_state import (
        CycleStateUnreadableError,
        read_last_cycle,
        read_last_cycle_with_status,
    )

    soul = tmp_path / "soul_map.json"
    soul.write_bytes(b"\xff\xfe")
    monkeypatch.setattr(weights, "SOUL_MAP_PATH", str(soul))
    monkeypatch.setattr(snaps, "_TICK_ACTIVE", True)
    assert read_last_cycle() == {}
    assert read_last_cycle_with_status() == ({}, "unreadable")
    with pytest.raises(CycleStateUnreadableError):
        snaps.producer_tick_progress()


def test_mutation_unreadable_legacy_must_not_look_like_idle_progress(
    tmp_path, monkeypatch
):
    from internal.council import scheduler_cycle_state as scs

    soul = tmp_path / "soul_map.json"
    soul.write_bytes(b"\xff\xfe")
    monkeypatch.setattr(weights, "SOUL_MAP_PATH", str(soul))

    real = scs._read_legacy_with_status

    def _hide_unreadable(soul_map_path=None):
        summary, unreadable = real(soul_map_path)
        if unreadable:
            return {}, False
        return summary, unreadable

    monkeypatch.setattr(scs, "_read_legacy_with_status", _hide_unreadable)
    assert scs.read_last_cycle_with_status() == ({}, "missing")


def test_empty_new_cycle_state_file_is_unreadable_not_missing(tmp_path, monkeypatch):
    from internal.council.scheduler_cycle_state import (
        read_last_cycle_with_status,
        scheduler_state_path,
    )

    soul = tmp_path / "soul_map.json"
    soul.write_text("{}")
    monkeypatch.setattr(weights, "SOUL_MAP_PATH", str(soul))
    Path(scheduler_state_path()).write_text("")
    assert read_last_cycle_with_status() == ({}, "unreadable")


def test_corrupt_new_cycle_file_falls_back_to_legacy_last_cycle(tmp_path, monkeypatch):
    from internal.council.scheduler_cycle_state import (
        read_last_cycle,
        read_last_cycle_with_status,
        scheduler_state_path,
    )

    legacy_cycle = {
        "run_at": "2026-01-01T00:00:00Z",
        "ok": True,
        "phase": "scoring",
        "progress": "3/128",
    }
    soul = tmp_path / "soul_map.json"
    soul.write_text(json.dumps({"score_snapshot_scheduler": {"last_cycle": legacy_cycle}}))
    monkeypatch.setattr(weights, "SOUL_MAP_PATH", str(soul))
    Path(scheduler_state_path()).write_text("{not json")
    assert read_last_cycle() == legacy_cycle
    assert read_last_cycle_with_status() == (legacy_cycle, "unreadable")


def test_mutation_corrupt_new_file_must_still_fallback_to_legacy(tmp_path, monkeypatch):
    from internal.council import scheduler_cycle_state as scs

    legacy_cycle = {"run_at": "2026-01-01T00:00:00Z", "ok": True}
    soul = tmp_path / "soul_map.json"
    soul.write_text(json.dumps({"score_snapshot_scheduler": {"last_cycle": legacy_cycle}}))
    monkeypatch.setattr(weights, "SOUL_MAP_PATH", str(soul))
    Path(scs.scheduler_state_path()).write_text("{not json")

    def _broken_read(soul_map_path=None):
        new, unreadable = scs._read_new(soul_map_path)
        if unreadable:
            return {}
        if new is not None:
            return dict(new)
        return scs._read_legacy(soul_map_path)

    monkeypatch.setattr(scs, "read_last_cycle", _broken_read)
    assert scs.read_last_cycle() == {}


# --- the scheduler's liveness record is the other thing a tick used to write into the soul_map ---


def _scheduler_over(tmp_path, monkeypatch, soul_text):
    from internal.store import soul_map_io

    soul = tmp_path / "soul_map.json"
    if soul_text is not None:
        soul.write_text(soul_text)
    monkeypatch.setattr(weights, "SOUL_MAP_PATH", str(soul))
    soul_map_io._cache.clear()
    return soul


def test_the_liveness_record_goes_to_its_own_file_and_survives_a_restart(tmp_path, monkeypatch):
    soul = _scheduler_over(tmp_path, monkeypatch, None)
    first = snaps.ScoreSnapshotScheduler()
    first.liveness.record_skip("heavy_job_busy")
    first.liveness.record_skip("heavy_job_busy")

    assert not soul.exists()
    own = json.loads((tmp_path / "score_snapshot_liveness.json").read_text())
    assert own["liveness"]["score_snapshot"]["consecutive_skips"] == 2
    assert snaps.ScoreSnapshotScheduler().liveness.snapshot()["consecutive_skips"] == 2


def test_a_legacy_liveness_record_in_the_soul_map_is_still_picked_up_after_the_deploy(tmp_path, monkeypatch):
    legacy = {"liveness": {"score_snapshot": {"lifecycle": "started", "consecutive_skips": 3, "last_event_epoch": 1.0}}}
    soul = _scheduler_over(tmp_path, monkeypatch, json.dumps(legacy))
    before = soul.read_bytes()

    sched = snaps.ScoreSnapshotScheduler()
    assert sched.liveness.snapshot()["consecutive_skips"] == 3
    sched.liveness.record_skip("heavy_job_busy")  # from here on it is recorded in the new file only

    assert soul.read_bytes() == before
    assert json.loads((tmp_path / "score_snapshot_liveness.json").read_text())["liveness"]["score_snapshot"]["consecutive_skips"] == 4


def test_other_trackers_still_persist_to_the_soul_map(tmp_path, monkeypatch):
    from internal.liveness import LivenessTracker

    soul = _scheduler_over(tmp_path, monkeypatch, "{}")
    LivenessTracker(name="other_scheduler_for_test", interval_seconds=60).record_skip("busy")
    assert json.loads(soul.read_text())["liveness"]["other_scheduler_for_test"]["consecutive_skips"] == 1
