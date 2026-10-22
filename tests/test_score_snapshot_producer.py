"""PR-A / MC #1479 D1 — essential-worker producer boot + idempotency."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

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
    )


def test_essential_worker_boot_publishes_complete_snapshot(tmp_path, monkeypatch):
    netuids = range(1, 129)
    membership = _membership_for_netuids(netuids)
    path = tmp_path / "score_snapshots.json"
    old_started = "2020-01-01T00:00:00Z"
    seed_rows = [{"netuid": n, "total_score": float(n)} for n in (1, 2, 3)]
    payload = complete_snapshot_payload(day_rows=seed_rows, hour_rows=seed_rows)
    payload["build_started_at"] = old_started
    path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(snaps, "SCORE_SNAPSHOTS_PATH", str(path))
    monkeypatch.setattr(snaps, "SCORE_SNAPSHOT_SEED_PATH", str(tmp_path / "no_seed.json"))
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
    hydrate = [{"netuid": n, "name": f"s{n}", "price": 1.0, "volume": 1000.0} for n in netuids]
    monkeypatch.setattr("server._get_subnets_hydrate", lambda: (hydrate, "registry-fallback"))
    soul = tmp_path / "soul_map.json"
    soul.write_text(
        json.dumps({"score_snapshot_scheduler": {"last_cycle": {"phase": "done", "ok": True}}}),
        encoding="utf-8",
    )
    monkeypatch.setattr("internal.council.weights.SOUL_MAP_PATH", str(soul))
    monkeypatch.setattr(snaps, "schedule_in_seconds", lambda *args, **kwargs: None)
    monkeypatch.setattr(snaps.ScoreSnapshotScheduler, "_scoring_in_progress", lambda self: False)

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
    out = sched.run_once()
    assert out.get("ok") is True
    assert out.get("complete") is True
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert on_disk["coverage"]["complete"] is True
    assert on_disk.get("build_started_at") and on_disk["build_started_at"] != old_started
    assert on_disk["count"] == len(netuids)
