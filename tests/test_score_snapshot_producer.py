"""PR-A / MC #1479 D1 — essential-worker producer boot + idempotency."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from internal.chain_read import ChainRead
from internal.council import score_snapshots as snaps
from internal.subnet_universe import UniverseSnapshot, _validity_entry
from tests.score_snapshot_testutil import complete_snapshot_payload


@pytest.fixture(autouse=True)
def _reset_score_snapshot_scheduler():
    from internal.job_scheduler import cancel_job
    from internal.store.soul_map_io import _cache as soul_map_cache

    snaps.stop_score_snapshot_scheduler()
    with snaps._lock:
        snaps._TICK_ACTIVE = False
        snaps._write_future = None
    soul_map_cache.clear()
    cancel_job(snaps.JOB_ID)
    yield
    snaps.stop_score_snapshot_scheduler()
    soul_map_cache.clear()
    cancel_job(snaps.JOB_ID)


def test_essential_worker_boot_arms_scheduler_not_ensure(monkeypatch, tmp_path):
    """Replit #1484 P1: essential WORKER_HEAVY must arm producer, not score-snapshot-ensure."""
    monkeypatch.setenv("RUN_MODE", "worker")
    monkeypatch.setenv("WORKER_HEAVY", "essential")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DATA_DIR_IS_VOLUME", "on")
    monkeypatch.setenv("SCORE_SNAPSHOT_BOOT_IMMEDIATE", "off")
    soul = tmp_path / "soul_map.json"
    soul.write_text("{}", encoding="utf-8")
    monkeypatch.setattr("internal.council.weights.SOUL_MAP_PATH", str(soul))
    defer_names: list[str] = []
    scheduled_jobs: list[str] = []

    def _defer(name, fn, delay=0):
        defer_names.append(name)
        if name == "score-snapshots":
            fn()

    monkeypatch.setattr("internal.background_boot.defer_boot", _defer)
    monkeypatch.setattr("internal.freshness.start_background_sync", MagicMock())
    monkeypatch.setattr(
        "internal.background_boot._start_pump_desk_snapshot_scheduler",
        MagicMock(),
    )
    for name in (
        "_start_pump_ladder",
        "_start_resolver",
        "_start_whale_warm_scheduler",
        "_start_pick_schedulers",
        "_maybe_start_message_intel",
        "_maybe_start_summary_bot",
        "_warm_judges_cache",
        "_start_pick_audit_scheduler",
        "_start_outcome_snapshot_scheduler",
        "_start_calibration_snapshot_scheduler",
        "_start_dev_radar_github_scheduler",
    ):
        monkeypatch.setattr(f"internal.background_boot.{name}", MagicMock())
    monkeypatch.setattr(snaps, "schedule_in_seconds", lambda job_id, _fn, _sec: scheduled_jobs.append(job_id))
    monkeypatch.setattr("internal.live_subnets.registry_ready", lambda: True)
    monkeypatch.setattr("internal.live_subnets.bootstrap_live_subnets_cache", MagicMock())
    monkeypatch.setattr("internal.live_subnets.start_live_subnets_sync", MagicMock())

    from internal.background_boot import start_background_workers

    start_background_workers()
    assert "score-snapshot-ensure" not in defer_names
    assert "score-snapshots" in defer_names
    assert snaps._scheduler is not None
    assert scheduled_jobs == [snaps.JOB_ID]


def test_second_start_in_process_does_not_spawn_a_second_tick(tmp_path, monkeypatch):
    soul = tmp_path / "soul_map.json"
    soul.write_text("{}", encoding="utf-8")
    monkeypatch.setattr("internal.council.weights.SOUL_MAP_PATH", str(soul))
    scheduled = []
    monkeypatch.setattr(
        snaps,
        "schedule_in_seconds",
        lambda job_id, func, seconds: scheduled.append((job_id, seconds)),
    )
    sched = snaps.ScoreSnapshotScheduler()
    with snaps._lock:
        snaps._scheduler = sched
    first = sched.start(immediate=False)
    second = sched.start(immediate=False)
    assert first["started"] is True
    assert second["started"] is False
    assert second["reason"] == "already_armed"
    assert len(scheduled) == 1


def test_failed_arm_leaves_scheduler_retryable(tmp_path, monkeypatch):
    soul = tmp_path / "soul_map.json"
    soul.write_text("{}", encoding="utf-8")
    monkeypatch.setattr("internal.council.weights.SOUL_MAP_PATH", str(soul))
    scheduled = []

    def flaky_schedule(job_id, func, seconds):
        if not scheduled:
            scheduled.append("failed")
            raise RuntimeError("scheduler unavailable")
        scheduled.append((job_id, seconds))

    monkeypatch.setattr(snaps, "schedule_in_seconds", flaky_schedule)
    sched = snaps.ScoreSnapshotScheduler()
    with snaps._lock:
        snaps._scheduler = sched
    with pytest.raises(RuntimeError):
        sched.start(immediate=False)
    retry = sched.start(immediate=False)
    assert retry["started"] is True
    assert scheduled[-1][0] == snaps.JOB_ID


def test_failed_arm_does_not_report_running(tmp_path, monkeypatch):
    soul = tmp_path / "soul_map.json"
    soul.write_text("{}", encoding="utf-8")
    monkeypatch.setattr("internal.council.weights.SOUL_MAP_PATH", str(soul))

    def failing_schedule(job_id, func, seconds):
        raise RuntimeError("scheduler unavailable")

    monkeypatch.setattr(snaps, "schedule_in_seconds", failing_schedule)
    sched = snaps.ScoreSnapshotScheduler()
    with snaps._lock:
        snaps._scheduler = sched
    with pytest.raises(RuntimeError):
        sched.start(immediate=False)
    assert sched.state()["running"] is False


def _membership_for_netuids(netuids: range) -> UniverseSnapshot:
    resolved = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    rows = tuple(
        {
            "netuid": n,
            "name": f"s{n}",
            "price": 1.0,
            "volume": 1000.0,
            "source": "taomarketcap",
        }
        for n in netuids
    )
    validity = {str(n): _validity_entry(validity="positive", sources=["taomarketcap"]) for n in netuids}
    return UniverseSnapshot(
        netuids=tuple(netuids),
        rows=rows,
        resolved_at=resolved,
        status="ok",
        degraded=False,
        cap_reached=False,
        refresh_incomplete=False,
        validity_map=validity,
        chain=ChainRead.parse({"block_hash": "0x" + "ab" * 32, "netuids": sorted(netuids)}),
    )


def _essential_worker_cycle_fixtures(tmp_path, monkeypatch, membership, seed_path, *, scheduled=None, soul=None):
    """Shared fixture set so a real cycle can run without chain or heavy-job access."""
    monkeypatch.setenv("SCORE_SNAPSHOT_CYCLE_PATH", str(tmp_path / "cycle.json"))
    monkeypatch.setenv("SCORE_SNAPSHOT_REGISTRY_ONLY", "on")
    monkeypatch.setenv("SCORE_SNAPSHOT_BOOT_IMMEDIATE", "off")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUN_MODE", "worker")
    monkeypatch.setenv("WORKER_HEAVY", "essential")
    monkeypatch.setattr("internal.subnet_universe.get_snapshot", lambda: membership)
    from internal.council import snapshot_coverage as cov

    monkeypatch.setattr(cov, "coverage_capture_deadline_seconds", lambda _start: True)

    def _day(sn, _ctx):
        return {"total_score": float(sn["netuid"])}

    monkeypatch.setattr("internal.council.state_vector.score_subnet_for_day", _day)
    monkeypatch.setattr("internal.council.state_vector.score_subnet_for_hour", _day)
    monkeypatch.setattr(snaps, "_score_hour_enabled", lambda: False)
    hydrate = [{"netuid": n, "name": f"s{n}", "price": 1.0, "volume": 1000.0} for n in membership.netuids]
    monkeypatch.setattr("server._get_subnets_hydrate", lambda: (hydrate, "registry-fallback"))

    def _capture(job_id, fn, seconds):
        if scheduled is not None:
            scheduled.append((job_id, fn))

    monkeypatch.setattr(snaps, "schedule_in_seconds", _capture)
    monkeypatch.setattr(snaps.ScoreSnapshotScheduler, "_scoring_in_progress", lambda self: False)
    soul_path = tmp_path / "soul_map.json"
    soul_path.write_text(json.dumps(soul if soul is not None else {}), encoding="utf-8")
    monkeypatch.setattr("internal.council.weights.SOUL_MAP_PATH", str(soul_path))
    return soul_path


@pytest.mark.parametrize("seed_only", [False, True], ids=["stale_volume_file", "seed_only_no_volume_file"])
def test_essential_worker_boot_publishes_complete_snapshot(tmp_path, monkeypatch, seed_only):
    netuids = range(1, 129)
    membership = _membership_for_netuids(netuids)
    path = tmp_path / "score_snapshots.json"
    old_started = "2020-01-01T00:00:00Z"
    seed_rows = [{"netuid": n, "total_score": float(n)} for n in (1, 2, 3)]
    payload = complete_snapshot_payload(day_rows=seed_rows, hour_rows=seed_rows)
    payload["build_started_at"] = old_started
    seed_path = tmp_path / "seed.json" if seed_only else tmp_path / "no_seed.json"
    (seed_path if seed_only else path).write_text(json.dumps(payload), encoding="utf-8")
    assert path.exists() is not seed_only
    monkeypatch.setattr(snaps, "SCORE_SNAPSHOTS_PATH", str(path))
    monkeypatch.setattr(snaps, "SCORE_SNAPSHOT_SEED_PATH", str(seed_path))
    _essential_worker_cycle_fixtures(
        tmp_path,
        monkeypatch,
        membership,
        seed_path,
        soul={"score_snapshot_scheduler": {"last_cycle": {"phase": "done", "ok": True}}},
    )

    score_boot_ran = {"n": 0}

    def _defer(name, fn, delay=0):
        if name == "score-snapshots":
            score_boot_ran["n"] += 1
            fn()

    monkeypatch.setattr("internal.background_boot.defer_boot", _defer)
    from internal.background_boot import _start_score_snapshot_scheduler

    _start_score_snapshot_scheduler()
    assert score_boot_ran["n"] == 1
    sched = snaps._scheduler
    assert sched is not None
    assert sched.liveness.snapshot().get("lifecycle") == "started"
    out = sched.run_once()
    assert out.get("ok") is True
    assert out.get("complete") is True
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert on_disk["coverage"]["complete"] is True
    assert on_disk.get("build_started_at") and on_disk["build_started_at"] != old_started
    assert on_disk["count"] == len(netuids)


def test_restart_with_fresh_snapshot_and_persisted_started_lifecycle_still_arms(tmp_path, monkeypatch):
    """Replit P1 (restart arming): a fresh complete volume file plus a persisted
    lifecycle=started must not keep the producer from re-arming after a restart.
    The ``start()`` returns early when the served state is FRESH mutation must fail here."""
    netuids = range(1, 129)
    membership = _membership_for_netuids(netuids)
    path = tmp_path / "score_snapshots.json"
    fresh_started = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    day_rows = [{"netuid": n, "total_score": float(n)} for n in netuids]
    payload = complete_snapshot_payload(day_rows=day_rows, hour_rows=day_rows)
    payload["build_started_at"] = fresh_started
    path.write_text(json.dumps(payload), encoding="utf-8")
    seed_path = tmp_path / "no_seed.json"
    monkeypatch.setattr(snaps, "SCORE_SNAPSHOTS_PATH", str(path))
    monkeypatch.setattr(snaps, "SCORE_SNAPSHOT_SEED_PATH", str(seed_path))
    scheduled: list = []
    _essential_worker_cycle_fixtures(
        tmp_path,
        monkeypatch,
        membership,
        seed_path,
        scheduled=scheduled,
        soul={
            "liveness": {
                "score_snapshot": {
                    "last_success_epoch": datetime.now(timezone.utc).timestamp(),
                    "last_event_epoch": datetime.now(timezone.utc).timestamp(),
                    "lifecycle": "started",
                    "consecutive_failures": 0,
                    "consecutive_skips": 0,
                    "last_error": None,
                    "last_evidence": {"count": len(netuids), "op": "score_snapshot"},
                    "updated_at": fresh_started,
                }
            },
            "score_snapshot_scheduler": {"last_cycle": {"phase": "done", "ok": True}},
        },
    )

    served = snaps.read_served_snapshot(path=str(path), seed_path=str(seed_path))
    assert served.state is snaps.ServedState.FRESH
    persisted = json.loads((tmp_path / "soul_map.json").read_text(encoding="utf-8"))
    assert persisted["liveness"]["score_snapshot"]["lifecycle"] == "started"

    def _defer(name, fn, delay=0):
        if name == "score-snapshots":
            fn()

    monkeypatch.setattr("internal.background_boot.defer_boot", _defer)
    from internal.background_boot import _start_score_snapshot_scheduler

    _start_score_snapshot_scheduler()
    sched = snaps._scheduler
    assert sched is not None
    assert [job_id for job_id, _ in scheduled] == [snaps.JOB_ID]
    assert sched.state()["running"] is True

    tick_fn = scheduled[0][1]
    tick_fn()
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert on_disk["coverage"]["complete"] is True
    assert on_disk["build_started_at"] != fresh_started
    assert on_disk["count"] == len(netuids)


def _stale_volume_file(tmp_path, monkeypatch) -> Path:
    path = tmp_path / "score_snapshots.json"
    payload = complete_snapshot_payload()
    payload["build_started_at"] = "2020-01-01T00:00:00Z"
    path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(snaps, "SCORE_SNAPSHOTS_PATH", str(path))
    monkeypatch.setattr(snaps, "SCORE_SNAPSHOT_SEED_PATH", str(tmp_path / "no_seed.json"))
    soul = tmp_path / "soul_map.json"
    soul.write_text("{}", encoding="utf-8")
    monkeypatch.setattr("internal.council.weights.SOUL_MAP_PATH", str(soul))
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    return path


@pytest.mark.parametrize(
    "env,revived",
    [
        ({"WORKER_HEAVY": "off"}, False),
        ({"STAGE2_HOP": "1", "WORKER_HEAVY": "essential"}, False),
        ({"WORKER_HEAVY": "essential"}, True),
    ],
    ids=["heavy_off", "hop", "essential_owner"],
)
def test_revive_runs_only_on_the_producer_owner(tmp_path, monkeypatch, env, revived):
    """MC blocker: stall-guard revive must not make a non-owner worker produce."""
    path = _stale_volume_file(tmp_path, monkeypatch)
    monkeypatch.setenv("RUN_MODE", "worker")
    monkeypatch.delenv("STAGE2_HOP", raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    ticks: list[int] = []
    monkeypatch.setattr(
        snaps.ScoreSnapshotScheduler,
        "run_once",
        lambda self: ticks.append(1) or {"ok": True, "skipped": True},
    )
    monkeypatch.setattr(snaps, "schedule_in_seconds", lambda *a, **k: None)

    out = snaps.revive_score_snapshot_scheduler()

    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
    if revived:
        assert ticks == [1]
        assert out["start"]["started"] is True
    else:
        assert ticks == []
        assert out["revived"] is False
        assert out["reason"] == "not_owner"
        assert snaps._scheduler is None
        assert snaps.start_score_snapshot_scheduler()["reason"] == "not_owner"
