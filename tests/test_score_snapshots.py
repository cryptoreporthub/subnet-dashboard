"""Phase 2 — full-universe score snapshots off the hot path."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from internal.council import score_snapshots as snaps
from tests.score_snapshot_testutil import chain_dict, complete_snapshot_payload


def test_save_load_and_rank(tmp_path, monkeypatch):
    path = tmp_path / "score_snapshots.json"
    monkeypatch.setattr(snaps, "SCORE_SNAPSHOTS_PATH", str(path))
    payload = complete_snapshot_payload(
        day_rows=[
            {"netuid": 99, "total_score": 90.0},
            {"netuid": 1, "total_score": 10.0},
            {"netuid": 50, "total_score": 50.0},
        ],
        written_at="2026-07-26T00:00:00Z",
    )
    payload["count"] = 3
    snaps.publish_complete_snapshot(payload, str(path))
    ranked = snaps.rank_subnets_by_snapshot(
        [{"netuid": 1}, {"netuid": 50}, {"netuid": 99}, {"netuid": 7}],
        path=str(path),
    )
    assert ranked is not None
    assert [r["netuid"] for r in ranked[:3]] == [99, 50, 1]


def test_stale_snapshot_is_still_served_as_aged(tmp_path, monkeypatch):
    from tests.score_snapshot_testutil import complete_snapshot_payload

    path = tmp_path / "score_snapshots.json"
    monkeypatch.setattr(snaps, "SCORE_SNAPSHOT_SEED_PATH", str(tmp_path / "no_seed.json"))
    snaps.publish_complete_snapshot(
        complete_snapshot_payload(
            day_rows=[{"netuid": 1, "total_score": 1.0}],
            written_at="2020-01-01T00:00:00Z",
        ),
        str(path),
    )
    ranked = snaps.rank_subnets_by_snapshot(
        [{"netuid": 1}],
        path=str(path),
        max_age_seconds=60,
    )
    assert ranked is not None
    served = snaps.read_served_snapshot(path=str(path), max_age_seconds=60)
    assert served.state.value == "aged"


def test_build_snapshot_scores_all(monkeypatch):
    def _hour(sn, ctx):
        return {"total_score": float(sn["netuid"])}

    def _day(sn, ctx):
        return {"total_score": float(sn["netuid"]) * 2}

    monkeypatch.setattr(
        "internal.council.state_vector.score_subnet_for_hour",
        _hour,
    )
    monkeypatch.setattr(
        "internal.council.state_vector.score_subnet_for_day",
        _day,
    )
    monkeypatch.setattr(
        "internal.subnets.tradable.tradable_subnets",
        lambda rows: rows,
    )
    subnets = [{"netuid": 3, "price": 1}, {"netuid": 8, "price": 1}]
    out = snaps.build_full_universe_snapshot(subnets, {})
    assert out["count"] == 2
    assert out["day"][0]["netuid"] == 8
    assert out["hour"][0]["netuid"] == 8


def test_boot_wires_snapshot_scheduler():
    boot = Path("internal/background_boot.py").read_text(encoding="utf-8")
    assert "_start_score_snapshot_scheduler" in boot
    assert "start_score_snapshot_scheduler" in boot


def test_scheduler_disabled(monkeypatch):
    monkeypatch.setenv("SCORE_SNAPSHOT_SCHEDULER_ENABLED", "off")
    snaps.stop_score_snapshot_scheduler()
    out = snaps.start_score_snapshot_scheduler()
    assert out["started"] is False


def test_tick_skips_when_gate_busy_without_blocking(tmp_path, monkeypatch):
    """Contended snapshot must skip (not wedge) and never touch the heavy gate."""
    from internal.heavy_job_gate import heavy_job_slot

    ran = {"n": 0}

    def _fail(**kwargs):
        ran["n"] += 1
        raise AssertionError("write_full_universe_snapshot must not run when gate busy")

    monkeypatch.setattr(snaps, "write_full_universe_snapshot", _fail)
    soul = tmp_path / "soul_map.json"
    soul.write_text("{}", encoding="utf-8")
    monkeypatch.setattr("internal.council.weights.SOUL_MAP_PATH", str(soul))

    sched = snaps.ScoreSnapshotScheduler()
    sched._scoring_in_progress = lambda: False
    with heavy_job_slot("other_heavy_job"):
        out = sched._tick(reschedule=False)
    assert out.get("skipped") == "heavy_job_busy"
    assert out.get("ok") is not True
    assert sched.liveness.snapshot()["consecutive_skips"] >= 1
    assert ran["n"] == 0


def test_tick_runs_cycle_when_gate_free(tmp_path, monkeypatch):
    """Ungated snapshot completes a full cycle and updates scheduler state."""
    soul = tmp_path / "soul_map.json"
    soul.write_text("{}", encoding="utf-8")
    monkeypatch.setattr("internal.council.weights.SOUL_MAP_PATH", str(soul))

    def _fake_write(progress_cb=None):
        if progress_cb:
            progress_cb(1, 1)
        return {
            "ok": True,
            "complete": True,
            "published": True,
            "count": 3,
            "written_at": "2026-08-07T00:00:00Z",
            "path": "data/score_snapshots.json",
        }

    monkeypatch.setattr(snaps, "write_full_universe_snapshot", _fake_write)
    sched = snaps.ScoreSnapshotScheduler()
    sched._scoring_in_progress = lambda: False
    out = sched._tick(reschedule=False)
    assert out.get("ok") is True
    assert out.get("count") == 3
    state = sched.state()
    assert state["liveness"]["status"] == "ok"
    assert state["last_result"]["count"] == 3


def test_persist_cycle_summary_writes_soul_map(tmp_path, monkeypatch):
    soul = tmp_path / "soul_map.json"
    soul.write_text("{}", encoding="utf-8")
    monkeypatch.setattr("internal.council.weights.SOUL_MAP_PATH", str(soul))
    sched = snaps.ScoreSnapshotScheduler()
    sched._persist_cycle_summary(
        {
            "run_at": "2026-07-26T12:00:00Z",
            "ok": True,
            "count": 42,
            "written_at": "2026-07-26T12:00:00Z",
            "path": "data/score_snapshots.json",
        }
    )
    data = json.loads(soul.read_text(encoding="utf-8"))
    last = data["score_snapshot_scheduler"]["last_cycle"]
    assert last["ok"] is True
    assert last["count"] == 42


def test_skipped_tick_persists_last_cycle(tmp_path, monkeypatch):
    soul = tmp_path / "soul_map.json"
    soul.write_text("{}", encoding="utf-8")
    monkeypatch.setattr("internal.council.weights.SOUL_MAP_PATH", str(soul))
    sched = snaps.ScoreSnapshotScheduler()
    sched._persist_cycle_summary(
        {"run_at": "2026-07-26T12:05:00Z", "ok": True, "skipped": "heavy_job_busy"}
    )
    data = json.loads(soul.read_text(encoding="utf-8"))
    last = data["score_snapshot_scheduler"]["last_cycle"]
    assert last.get("skipped") == "heavy_job_busy"


def test_build_snapshot_day_only_skips_hour_scoring(monkeypatch):
    hour_calls = 0

    def _hour(sn, ctx):
        nonlocal hour_calls
        hour_calls += 1
        return {"total_score": 1.0}

    monkeypatch.setattr(
        "internal.council.state_vector.score_subnet_for_hour",
        _hour,
    )
    monkeypatch.setattr(
        "internal.council.state_vector.score_subnet_for_day",
        lambda sn, ctx: {"total_score": 2.0},
    )
    monkeypatch.setattr(
        "internal.subnets.tradable.tradable_subnets",
        lambda rows: rows,
    )
    out = snaps.build_full_universe_snapshot([{"netuid": 3, "name": "A"}], {}, score_hour=False)
    assert hour_calls == 0
    assert out["day"][0]["netuid"] == 3
    assert out["hour"][0]["netuid"] == 3


def test_write_snapshot_prefers_registry_when_enabled(monkeypatch, tmp_path):
    path = tmp_path / "score_snapshots.json"
    monkeypatch.setattr(snaps, "SCORE_SNAPSHOTS_PATH", str(path))
    monkeypatch.setattr(snaps, "SCORE_SNAPSHOT_SEED_PATH", str(tmp_path / "no_seed.json"))
    hydrate = [{"netuid": 5, "name": "Five", "price": 1.0, "volume": 1000.0}]
    _patch_write_membership(monkeypatch, [5])
    monkeypatch.setenv("SCORE_SNAPSHOT_REGISTRY_ONLY", "on")

    def _live_fail(**_kwargs):
        raise AssertionError("live feed should not run when registry-only")

    monkeypatch.setattr("server._get_subnets_hydrate", lambda: (hydrate, "registry-fallback"))
    monkeypatch.setattr("server._get_subnets_with_source", _live_fail)
    monkeypatch.setattr(
        "internal.council.state_vector.score_subnet_for_hour",
        lambda sn, ctx: {"total_score": 1.0},
    )
    monkeypatch.setattr(
        "internal.council.state_vector.score_subnet_for_day",
        lambda sn, ctx: {"total_score": 2.0},
    )
    monkeypatch.setattr(
        "internal.subnets.tradable.tradable_subnets",
        lambda rows: rows,
    )
    out = snaps.write_full_universe_snapshot()
    assert out["ok"] is True
    assert path.is_file()


def test_immediate_write_completion_no_deadlock(monkeypatch, tmp_path):
    """Already-done future must not deadlock when registering the release callback."""
    from concurrent.futures import Future, ThreadPoolExecutor

    path = tmp_path / "score_snapshots.json"
    monkeypatch.setattr(snaps, "SCORE_SNAPSHOTS_PATH", str(path))
    monkeypatch.setattr(snaps, "SCORE_SNAPSHOT_SEED_PATH", str(tmp_path / "no_seed.json"))
    monkeypatch.setattr(snaps, "SCORE_SNAPSHOT_WRITE_TIMEOUT_SECONDS", 30)
    monkeypatch.setenv("SCORE_SNAPSHOT_REGISTRY_ONLY", "on")
    _patch_write_membership(monkeypatch, [1])
    monkeypatch.setattr(
        "server._get_subnets_hydrate",
        lambda: ([{"netuid": 1, "name": "One", "price": 1.0, "volume": 1000.0}], "registry-fallback"),
    )
    monkeypatch.setattr(
        "internal.council.state_vector.score_subnet_for_hour",
        lambda sn, ctx: {"total_score": 1.0},
    )
    monkeypatch.setattr(
        "internal.council.state_vector.score_subnet_for_day",
        lambda sn, ctx: {"total_score": 2.0},
    )
    monkeypatch.setattr(
        "internal.subnets.tradable.tradable_subnets",
        lambda rows: rows,
    )

    class _RaceExecutor(ThreadPoolExecutor):
        def submit(self, fn, *args, **kwargs):
            fut = Future()
            try:
                fut.set_result(fn(*args, **kwargs))
            except Exception as exc:
                fut.set_exception(exc)
            return fut

    monkeypatch.setattr(snaps, "ThreadPoolExecutor", _RaceExecutor)
    _reset_write_occupancy()

    result: dict[str, object] = {}

    def _run() -> None:
        result["out"] = snaps.write_full_universe_snapshot()

    import threading

    worker = threading.Thread(target=_run)
    worker.start()
    worker.join(timeout=2.0)
    assert not worker.is_alive(), "write_full_universe_snapshot deadlocked on fast completion"
    out = result.get("out")
    assert isinstance(out, dict)
    assert out.get("ok") is True
    assert path.is_file()


def test_write_snapshot_times_out(monkeypatch, tmp_path, caplog):
    caplog.set_level(logging.INFO, logger="internal.council.score_snapshots")
    path = tmp_path / "score_snapshots.json"
    monkeypatch.setattr(snaps, "SCORE_SNAPSHOTS_PATH", str(path))
    monkeypatch.setattr(snaps, "SCORE_SNAPSHOT_WRITE_TIMEOUT_SECONDS", 1)
    hydrate = [{"netuid": 5, "name": "Five"}]
    monkeypatch.setenv("SCORE_SNAPSHOT_REGISTRY_ONLY", "on")

    def _hang(*_args, **_kwargs):
        time.sleep(3)
        return {"count": 1, "written_at": "t", "hour": [], "day": []}

    monkeypatch.setattr("server._get_subnets_hydrate", lambda: (hydrate, "registry-fallback"))
    monkeypatch.setattr(snaps, "build_full_universe_snapshot", _hang)
    out = snaps.write_full_universe_snapshot()
    assert out["ok"] is False
    assert "write_timeout" in out.get("error", "")
    assert not path.is_file()
    time.sleep(3.5)  # drain singleton executor slot after timeout
    messages = [record.getMessage() for record in caplog.records]
    assert any("completed-after-abandon" in message for message in messages)
    assert any("duration=" in message and "started_at=" in message for message in messages)


def _reset_write_occupancy() -> None:
    deadline = time.time() + 6
    while snaps._scoring_write_in_progress() and time.time() < deadline:
        time.sleep(0.1)
    snaps._TICK_ACTIVE = False
    with snaps._lock:
        snaps._write_future = None


def _wire_scheduler_paths(tmp_path, monkeypatch):
    path = tmp_path / "score_snapshots.json"
    soul = tmp_path / "soul_map.json"
    soul.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(snaps, "SCORE_SNAPSHOTS_PATH", str(path))
    monkeypatch.setattr(snaps, "SCORE_SNAPSHOT_SEED_PATH", str(tmp_path / "no_seed.json"))
    monkeypatch.setenv("SCORE_SNAPSHOT_CYCLE_PATH", str(tmp_path / "cycle.json"))
    monkeypatch.setattr("internal.council.weights.SOUL_MAP_PATH", str(soul))
    monkeypatch.setattr(snaps, "SCORE_SNAPSHOT_WRITE_TIMEOUT_SECONDS", 1)
    monkeypatch.setenv("SCORE_SNAPSHOT_REGISTRY_ONLY", "on")
    monkeypatch.setattr(
        "server._get_subnets_hydrate",
        lambda: (
            [{"netuid": 1, "name": "One", "price": 1.0, "volume": 1000.0}],
            "registry-fallback",
        ),
    )
    monkeypatch.setattr(
        "internal.council.snapshot_coverage.load_membership_receipt",
        lambda: {
            "expected_netuids": [1],
            "chain": chain_dict([1]),
            "fresh": True,
            "degraded": False,
            "cap_reached": False,
            "refresh_incomplete": False,
        },
    )
    return path


def _patch_write_membership(monkeypatch, netuids):
    monkeypatch.setattr(
        "internal.council.snapshot_coverage.load_membership_receipt",
        lambda: {
            "expected_netuids": list(netuids),
            "chain": chain_dict(netuids),
            "fresh": True,
            "degraded": False,
            "cap_reached": False,
            "refresh_incomplete": False,
        },
    )


def _published_payload(**kwargs):
    base = complete_snapshot_payload(
        day_rows=kwargs.pop("day_rows", [{"netuid": 1, "total_score": 1.0}]),
        written_at=kwargs.pop("written_at", "2026-08-21T00:00:00Z"),
    )
    base.update(kwargs)
    return base


def test_timeout_second_tick_skips_second_write(monkeypatch, tmp_path):
    """After write_timeout, another tick must not submit a second universe write."""
    path = _wire_scheduler_paths(tmp_path, monkeypatch)
    write_calls = {"n": 0}

    def _slow_build(*_args, **_kwargs):
        write_calls["n"] += 1
        time.sleep(3)
        payload = _published_payload(count=1)
        snaps.publish_complete_snapshot(payload, str(path))
        return payload

    monkeypatch.setattr(snaps, "build_full_universe_snapshot", _slow_build)
    _reset_write_occupancy()
    sched = snaps.ScoreSnapshotScheduler()
    sched._scoring_in_progress = lambda: False

    first = sched.run_once()
    assert first.get("ok") is False
    assert "write_timeout" in first.get("error", "")
    assert write_calls["n"] == 1
    assert snaps._scoring_write_in_progress()

    second = sched.run_once()
    assert second.get("skipped") == "scoring_in_progress"
    assert write_calls["n"] == 1

    time.sleep(3.5)
    assert path.is_file()
    assert not snaps._scoring_write_in_progress()
    assert snaps._TICK_ACTIVE is False


def test_timeout_deferred_completion_allows_later_tick(monkeypatch, tmp_path):
    """When the timed-out write finishes, occupancy clears and a later tick may run."""
    path = _wire_scheduler_paths(tmp_path, monkeypatch)
    write_calls = {"n": 0}

    def _slow_build(*_args, **_kwargs):
        write_calls["n"] += 1
        time.sleep(2)
        payload = _published_payload(count=1)
        snaps.publish_complete_snapshot(payload, str(path))
        return payload

    monkeypatch.setattr(snaps, "build_full_universe_snapshot", _slow_build)
    _reset_write_occupancy()
    sched = snaps.ScoreSnapshotScheduler()
    sched._scoring_in_progress = lambda: False

    timed_out = sched.run_once()
    assert "write_timeout" in timed_out.get("error", "")
    assert write_calls["n"] == 1

    time.sleep(2.5)
    assert path.is_file()
    assert not snaps._scoring_write_in_progress()

    def _fast_write(**_kwargs):
        write_calls["n"] += 1
        payload = _published_payload(count=1)
        pub = snaps.publish_complete_snapshot(payload, str(path))
        return {
            "ok": True,
            "published": pub.get("published"),
            "complete": True,
            "count": 1,
            "path": str(path),
            "written_at": payload.get("written_at"),
            "coverage": payload.get("coverage"),
        }

    monkeypatch.setattr(snaps, "write_full_universe_snapshot", _fast_write)
    third = sched.run_once()
    assert third.get("ok") is True
    assert write_calls["n"] == 2


def test_register_completion_clears_occupancy_if_future_already_gone(tmp_path, monkeypatch):
    """Race: write released between occupancy check and callback register."""
    _wire_scheduler_paths(tmp_path, monkeypatch)
    _reset_write_occupancy()
    scheduled = []
    monkeypatch.setattr(
        snaps,
        "schedule_in_seconds",
        lambda job_id, func, seconds: scheduled.append((job_id, seconds)),
    )
    sched = snaps.ScoreSnapshotScheduler()
    snaps._scheduler = sched
    snaps._TICK_ACTIVE = True
    sched._tick_active = True
    with snaps._lock:
        snaps._write_future = None
    try:
        sched._register_write_completion_callback(reschedule=False)
        assert snaps._TICK_ACTIVE is False
        assert sched._tick_active is False
        assert scheduled
        assert scheduled[0][0] == snaps.JOB_ID
    finally:
        snaps._scheduler = None


def test_timeout_deferred_completion_rearms_when_registered(monkeypatch, tmp_path):
    """Timed-out run_once must still DateTrigger-rearm when the late write finishes."""
    path = _wire_scheduler_paths(tmp_path, monkeypatch)
    scheduled = []
    monkeypatch.setattr(
        snaps,
        "schedule_in_seconds",
        lambda job_id, func, seconds: scheduled.append((job_id, seconds)),
    )
    write_calls = {"n": 0}

    def _slow_build(*_args, **_kwargs):
        write_calls["n"] += 1
        time.sleep(2)
        payload = _published_payload(count=1)
        snaps.publish_complete_snapshot(payload, str(path))
        return payload

    monkeypatch.setattr(snaps, "build_full_universe_snapshot", _slow_build)
    _reset_write_occupancy()
    sched = snaps.ScoreSnapshotScheduler()
    snaps._scheduler = sched
    sched._scoring_in_progress = lambda: False
    try:
        timed_out = sched.run_once()
        assert "write_timeout" in timed_out.get("error", "")
        assert write_calls["n"] == 1
        assert scheduled == []
        deadline = time.time() + 5
        while not scheduled and time.time() < deadline:
            time.sleep(0.05)
        assert scheduled, "deferred completion must re-arm DateTrigger"
        assert scheduled[0][0] == snaps.JOB_ID
        assert path.is_file()
    finally:
        snaps._scheduler = None
        _reset_write_occupancy()


def test_start_does_not_schedule_when_not_registered(monkeypatch):
    scheduled = []
    monkeypatch.setattr(
        snaps,
        "schedule_in_seconds",
        lambda *a, **k: scheduled.append(a),
    )
    snaps._scheduler = None
    sched = snaps.ScoreSnapshotScheduler()
    out = sched.start(immediate=False)
    assert out["started"] is False
    assert out["reason"] == "not registered"
    assert scheduled == []


def test_start_schedules_when_persisted_lifecycle_started(tmp_path, monkeypatch):
    soul = tmp_path / "soul_map.json"
    soul.write_text("{}", encoding="utf-8")
    monkeypatch.setattr("internal.council.weights.SOUL_MAP_PATH", str(soul))
    scheduled = []
    monkeypatch.setattr(
        snaps,
        "schedule_in_seconds",
        lambda job_id, func, seconds: scheduled.append((job_id, seconds)),
    )
    snaps.stop_score_snapshot_scheduler()
    sched = snaps.ScoreSnapshotScheduler()
    snaps._scheduler = sched
    sched.liveness.start()
    assert sched.liveness.snapshot().get("lifecycle") == "started"
    try:
        out = sched.start(immediate=False)
        assert scheduled
        assert scheduled[0][0] == snaps.JOB_ID
        assert out["started"] is False
        assert out["reason"] == "already running"
    finally:
        snaps._scheduler = None


def test_module_start_schedules_when_lifecycle_started(tmp_path, monkeypatch):
    soul = tmp_path / "soul_map.json"
    soul.write_text("{}", encoding="utf-8")
    monkeypatch.setattr("internal.council.weights.SOUL_MAP_PATH", str(soul))
    scheduled = []
    monkeypatch.setattr(
        snaps,
        "schedule_in_seconds",
        lambda job_id, func, seconds: scheduled.append((job_id, seconds)),
    )
    snaps.stop_score_snapshot_scheduler()
    sched = snaps.ScoreSnapshotScheduler()
    with snaps._lock:
        snaps._scheduler = sched
    sched.liveness.start()
    try:
        out = snaps.start_score_snapshot_scheduler(immediate=False)
        assert scheduled
        assert scheduled[0][0] == snaps.JOB_ID
        assert out["started"] is False
        assert out["reason"] == "already running"
    finally:
        snaps.stop_score_snapshot_scheduler()


def test_build_snapshot_loads_pump_state_once(monkeypatch, tmp_path):
    """Per-build pump ladder state: one load_state per build_full_universe_snapshot."""
    load_calls = {"n": 0}
    pump_state = {
        "subnets": {
            "3": {"netuid": 3, "phase": "PUMPING", "composite_score": 0.8},
            "8": {"netuid": 8, "phase": "DORMANT", "composite_score": 0.1},
        }
    }

    def _load_state(path=None):
        load_calls["n"] += 1
        return pump_state

    monkeypatch.setattr("internal.pump.state.load_state", _load_state)

    overlay_calls = {"n": 0}

    def _day(sn, ctx):
        from internal.council.pump_overlay import apply_pump_score_overlay

        overlay_calls["n"] += 1
        total, _ = apply_pump_score_overlay(
            50.0, sn, pump_ladder_state=ctx.get("pump_ladder_state")
        )
        return {"total_score": total}

    monkeypatch.setattr("internal.council.state_vector.score_subnet_for_day", _day)
    monkeypatch.setattr(
        "internal.council.state_vector.score_subnet_for_hour",
        lambda sn, ctx: {"total_score": 1.0},
    )
    monkeypatch.setattr("internal.subnets.tradable.tradable_subnets", lambda rows: rows)
    subnets = [{"netuid": 3}, {"netuid": 8}, {"netuid": 12}]
    out = snaps.build_full_universe_snapshot(subnets, {}, score_hour=False)
    assert load_calls["n"] == 1
    assert overlay_calls["n"] == 3
    timing = out.get("build_stage_timing") or {}
    assert timing.get("pump_state_load_seconds") is not None


def test_build_snapshot_pump_overlay_matches_per_subnet_load(monkeypatch, tmp_path):
    """Run-scoped state must not change overlay scores vs per-subnet load_state."""
    pump_state = {
        "subnets": {
            "5": {"netuid": 5, "phase": "STIRRING", "composite_score": 0.6},
        }
    }
    monkeypatch.setattr("internal.pump.state.load_state", lambda path=None: pump_state)
    monkeypatch.setenv("PUMP_SCORE_OVERLAY_ALPHA", "0.10")

    def _day_scoped(sn, ctx):
        from internal.council.pump_overlay import apply_pump_score_overlay

        total, _ = apply_pump_score_overlay(
            40.0, sn, pump_ladder_state=ctx.get("pump_ladder_state")
        )
        return {"total_score": total}

    def _day_legacy(sn, _ctx):
        from internal.council.pump_overlay import apply_pump_score_overlay

        total, _ = apply_pump_score_overlay(40.0, sn)
        return {"total_score": total}

    monkeypatch.setattr("internal.subnets.tradable.tradable_subnets", lambda rows: rows)
    subnets = [{"netuid": 5}, {"netuid": 99}]
    monkeypatch.setattr("internal.council.state_vector.score_subnet_for_day", _day_scoped)
    scoped = snaps.build_full_universe_snapshot(subnets, {}, score_hour=False)
    monkeypatch.setattr("internal.council.state_vector.score_subnet_for_day", _day_legacy)
    legacy = snaps.build_full_universe_snapshot(subnets, {}, score_hour=False)
    scoped_scores = {r["netuid"]: r["total_score"] for r in scoped["day"]}
    legacy_scores = {r["netuid"]: r["total_score"] for r in legacy["day"]}
    assert scoped_scores == legacy_scores


def test_build_snapshot_refreshes_pump_state_on_next_build(monkeypatch):
    """Separate builds must re-read ladder state (no cross-build cache)."""
    versions = [
        {"subnets": {"7": {"netuid": 7, "phase": "PUMPING", "composite_score": 0.9}}},
        {"subnets": {"7": {"netuid": 7, "phase": "DORMANT", "composite_score": 0.1}}},
    ]
    load_calls = {"n": 0}

    def _load_state(path=None):
        load_calls["n"] += 1
        return versions[min(load_calls["n"] - 1, len(versions) - 1)]

    monkeypatch.setattr("internal.pump.state.load_state", _load_state)
    monkeypatch.setenv("PUMP_SCORE_OVERLAY_ALPHA", "0.10")

    def _day(sn, ctx):
        from internal.council.pump_overlay import apply_pump_score_overlay

        total, _ = apply_pump_score_overlay(
            60.0, sn, pump_ladder_state=ctx.get("pump_ladder_state")
        )
        return {"total_score": total}

    monkeypatch.setattr("internal.council.state_vector.score_subnet_for_day", _day)
    monkeypatch.setattr(
        "internal.council.state_vector.score_subnet_for_hour",
        lambda sn, ctx: {"total_score": 1.0},
    )
    monkeypatch.setattr(
        "internal.subnets.tradable.tradable_subnets",
        lambda rows: rows,
    )
    subnets = [{"netuid": 7}]
    first = snaps.build_full_universe_snapshot(subnets, {}, score_hour=False)
    second = snaps.build_full_universe_snapshot(subnets, {}, score_hour=False)
    assert load_calls["n"] == 2
    first_score = next(r["total_score"] for r in first["day"] if r["netuid"] == 7)
    second_score = next(r["total_score"] for r in second["day"] if r["netuid"] == 7)
    assert first_score != second_score


def test_day_scoring_seconds_excludes_hour_latency(monkeypatch):
    """day_scoring_seconds is sum of per-row day scorer time, not loop wall clock."""
    hour_delay = 0.05

    def _hour(sn, ctx):
        time.sleep(hour_delay)
        return {"total_score": 1.0}

    def _day(sn, ctx):
        return {"total_score": 2.0}

    monkeypatch.setattr(
        "internal.council.state_vector.score_subnet_for_hour",
        _hour,
    )
    monkeypatch.setattr(
        "internal.council.state_vector.score_subnet_for_day",
        _day,
    )
    monkeypatch.setattr(
        "internal.subnets.tradable.tradable_subnets",
        lambda rows: rows,
    )
    subnets = [{"netuid": i} for i in range(3)]
    out_with_hour = snaps.build_full_universe_snapshot(subnets, {}, score_hour=True)
    out_day_only = snaps.build_full_universe_snapshot(subnets, {}, score_hour=False)
    timing_hour = out_with_hour.get("build_stage_timing") or {}
    timing_day = out_day_only.get("build_stage_timing") or {}
    day_with = timing_hour.get("day_scoring_seconds") or 0.0
    day_without = timing_day.get("day_scoring_seconds") or 0.0
    hour_metric = timing_hour.get("hour_scoring_seconds") or 0.0
    loop_wall = timing_hour.get("subnet_scoring_loop_wall_seconds") or 0.0
    assert hour_metric >= hour_delay * len(subnets) * 0.9
    assert abs(day_with - day_without) < 0.01
    assert loop_wall >= hour_metric + day_with * 0.9


def test_write_snapshot_includes_stage_timing(monkeypatch, tmp_path):
    path = tmp_path / "score_snapshots.json"
    monkeypatch.setattr(snaps, "SCORE_SNAPSHOTS_PATH", str(path))
    monkeypatch.setattr(snaps, "SCORE_SNAPSHOT_SEED_PATH", str(tmp_path / "no_seed.json"))
    monkeypatch.setenv("SCORE_SNAPSHOT_REGISTRY_ONLY", "on")
    _patch_write_membership(monkeypatch, [2])
    monkeypatch.setattr(
        "server._get_subnets_hydrate",
        lambda: ([{"netuid": 2, "name": "Two", "price": 1.0, "volume": 1000.0}], "registry-fallback"),
    )
    monkeypatch.setattr(
        "internal.council.state_vector.score_subnet_for_hour",
        lambda sn, ctx: {"total_score": 1.0},
    )
    monkeypatch.setattr(
        "internal.council.state_vector.score_subnet_for_day",
        lambda sn, ctx: {"total_score": 2.0},
    )
    monkeypatch.setattr("internal.subnets.tradable.tradable_subnets", lambda rows: rows)
    monkeypatch.setattr("internal.pump.state.load_state", lambda path=None: {"subnets": {}})
    out = snaps.write_full_universe_snapshot()
    assert out["ok"] is True
    saved = json.loads(path.read_text(encoding="utf-8"))
    timing = (saved.get("coverage") or {}).get("timing") or {}
    assert timing.get("pump_state_load_seconds") is not None
    assert timing.get("day_scoring_seconds") is not None


def test_score_snapshot_tracker_is_liveness_compliant(monkeypatch, tmp_path):
    from tests.liveness_conformance import assert_liveness_compliant

    soul = tmp_path / "soul_map.json"
    soul.write_text("{}")
    monkeypatch.setattr("internal.council.weights.SOUL_MAP_PATH", str(soul))

    def factory():
        return snaps.ScoreSnapshotScheduler().liveness

    assert_liveness_compliant(factory)


def test_load_score_snapshot_returns_an_independent_copy_on_every_read(tmp_path):
    path = tmp_path / "snap.json"
    payload = complete_snapshot_payload(day_rows=[{"netuid": 1, "total_score": 5.0}])
    path.write_text(json.dumps(payload), encoding="utf-8")

    fresh_load = snaps.load_score_snapshot(str(path))
    fresh_load["day"][0]["total_score"] = -1.0
    fresh_load["coverage"]["day"]["expected"].append(999)

    cache_hit = snaps.load_score_snapshot(str(path))
    assert cache_hit["day"][0]["total_score"] == 5.0
    assert cache_hit["coverage"]["day"]["expected"] == [1]

    cache_hit["day"][0]["total_score"] = -2.0
    again = snaps.load_score_snapshot(str(path))
    assert again["day"][0]["total_score"] == 5.0
