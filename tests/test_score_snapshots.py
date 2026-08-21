"""Phase 2 — full-universe score snapshots off the hot path."""

from __future__ import annotations

import json
import time
from pathlib import Path

from internal.council import score_snapshots as snaps


def test_save_load_and_rank(tmp_path, monkeypatch):
    path = tmp_path / "score_snapshots.json"
    monkeypatch.setattr(snaps, "SCORE_SNAPSHOTS_PATH", str(path))
    payload = {
        "written_at": "2026-07-26T00:00:00Z",
        "count": 3,
        "hour": [],
        "day": [
            {"netuid": 99, "total_score": 90.0},
            {"netuid": 1, "total_score": 10.0},
            {"netuid": 50, "total_score": 50.0},
        ],
    }
    snaps.save_score_snapshot(payload, str(path))
    ranked = snaps.rank_subnets_by_snapshot(
        [{"netuid": 1}, {"netuid": 50}, {"netuid": 99}, {"netuid": 7}],
        path=str(path),
    )
    assert ranked is not None
    assert [r["netuid"] for r in ranked[:3]] == [99, 50, 1]


def test_stale_snapshot_returns_none(tmp_path, monkeypatch):
    path = tmp_path / "score_snapshots.json"
    snaps.save_score_snapshot(
        {"day": [{"netuid": 1, "total_score": 1.0}], "hour": []},
        str(path),
    )
    # Force mtime into the past
    old = time.time() - 10_000
    os_utime = __import__("os").utime
    os_utime(path, (old, old))
    ranked = snaps.rank_subnets_by_snapshot(
        [{"netuid": 1}],
        path=str(path),
        max_age_seconds=60,
    )
    assert ranked is None


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


def test_cap_prefers_snapshot(monkeypatch, tmp_path):
    path = tmp_path / "score_snapshots.json"
    snaps.save_score_snapshot(
        {
            "day": [
                {"netuid": 77, "total_score": 99},
                {"netuid": 2, "total_score": 1},
            ],
            "hour": [],
        },
        str(path),
    )
    monkeypatch.setattr(snaps, "SCORE_SNAPSHOTS_PATH", str(path))
    monkeypatch.setenv("SCORE_SNAPSHOTS_PATH", str(path))

    # Many low-volume rows; snapshot should promote 77 into the cap.
    rows = [{"netuid": i, "price": 1.0, "volume_24h": 1.0, "emission": 0.01} for i in range(1, 50)]
    rows.append({"netuid": 77, "price": 1.0, "volume_24h": 0.0, "emission": 0.0})

    from server import _cap_subnets_for_scoring

    capped = _cap_subnets_for_scoring(rows, limit=5)
    assert capped[0]["netuid"] == 77


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
    assert out.get("ok") is True
    assert ran["n"] == 0


def test_tick_runs_cycle_when_gate_free(tmp_path, monkeypatch):
    """Ungated snapshot completes a full cycle and updates scheduler state."""
    soul = tmp_path / "soul_map.json"
    soul.write_text("{}", encoding="utf-8")
    monkeypatch.setattr("internal.council.weights.SOUL_MAP_PATH", str(soul))

    def _fake_write(progress_cb=None):
        if progress_cb:
            progress_cb(1, 1)
        return {"ok": True, "count": 3, "written_at": "2026-08-07T00:00:00Z", "path": "data/score_snapshots.json"}

    monkeypatch.setattr(snaps, "write_full_universe_snapshot", _fake_write)
    sched = snaps.ScoreSnapshotScheduler()
    sched._scoring_in_progress = lambda: False
    out = sched._tick(reschedule=False)
    assert out.get("ok") is True
    assert out.get("count") == 3
    state = sched.state()
    assert state["last_run_ok"] is True
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
    hydrate = [{"netuid": 5, "name": "Five"}]
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


def test_snapshot_subnet_cap_defaults_on_worker(monkeypatch):
    monkeypatch.delenv("SCORE_SNAPSHOT_MAX_SUBNETS", raising=False)
    monkeypatch.setenv("TOP_SCORING_UNIVERSE", "5")
    monkeypatch.setattr("internal.run_mode.is_worker_mode", lambda: True)
    assert snaps._snapshot_subnet_cap() == 5


def test_write_snapshot_times_out(monkeypatch, tmp_path):
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
    monkeypatch.setattr("internal.council.weights.SOUL_MAP_PATH", str(soul))
    monkeypatch.setattr(snaps, "SCORE_SNAPSHOT_WRITE_TIMEOUT_SECONDS", 1)
    monkeypatch.setenv("SCORE_SNAPSHOT_REGISTRY_ONLY", "on")
    monkeypatch.setattr(
        "server._get_subnets_hydrate",
        lambda: ([{"netuid": 1, "name": "One"}], "registry-fallback"),
    )
    return path


def test_timeout_second_tick_skips_second_write(monkeypatch, tmp_path):
    """After write_timeout, another tick must not submit a second universe write."""
    path = _wire_scheduler_paths(tmp_path, monkeypatch)
    write_calls = {"n": 0}

    def _slow_build(*_args, **_kwargs):
        write_calls["n"] += 1
        time.sleep(3)
        payload = {
            "written_at": "2026-08-21T00:00:00Z",
            "count": 1,
            "hour": [],
            "day": [{"netuid": 1, "total_score": 1.0}],
        }
        snaps.save_score_snapshot(payload, str(path))
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
        payload = {
            "written_at": "2026-08-21T00:00:00Z",
            "count": 1,
            "hour": [],
            "day": [{"netuid": 1, "total_score": 1.0}],
        }
        snaps.save_score_snapshot(payload, str(path))
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

    def _fast_build(*_args, **_kwargs):
        write_calls["n"] += 1
        payload = {
            "written_at": "2026-08-21T01:00:00Z",
            "count": 2,
            "hour": [],
            "day": [{"netuid": 2, "total_score": 2.0}],
        }
        snaps.save_score_snapshot(payload, str(path))
        return payload

    monkeypatch.setattr(snaps, "build_full_universe_snapshot", _fast_build)
    third = sched.run_once()
    assert third.get("ok") is True
    assert write_calls["n"] == 2
