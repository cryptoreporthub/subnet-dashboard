"""Deploy blocker regressions (#1629): scheduler, postmortems, retrain fire, SimiVision."""

from __future__ import annotations

import fcntl
import json
import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any, List

import pytest
from fastapi.testclient import TestClient

import internal.indicators.indicator_scheduler as indicator_scheduler
import internal.judges.postmortems as postmortems
import internal.judges.tracker as tracker
from internal.calibration import pipeline as cal
from internal.calibration.pipeline import FireError
from internal.council import weights as council_weights
from internal.store import soul_map_io
from internal.store.soul_map_io import SoulMapLockWaitTimeout
from server import app

PREDICTION = {
    "id": "pred-blocker-1",
    "netuid": 3,
    "name": "Blocker Test",
    "direction": "up",
    "predicted_pct": 2.0,
    "reference_price": 100.0,
    "resolved_price": 95.0,
    "horizon_hours": 1,
    "outcome": "miss",
    "correct": False,
    "created_at": "2026-07-01T00:00:00Z",
}


@pytest.fixture
def pm_dir(tmp_path, monkeypatch):
    directory = tmp_path / "postmortems"
    directory.mkdir()
    monkeypatch.setattr(postmortems, "POSTMORTEMS_DIR", str(directory))
    return directory


@pytest.fixture
def portfolio_path(tmp_path, monkeypatch):
    path = tmp_path / "judge_portfolios.json"
    monkeypatch.setattr(
        "internal.judges.portfolios.PORTFOLIOS_PATH",
        str(path),
    )
    return path


@pytest.fixture
def soul_path(tmp_path, monkeypatch):
    path = tmp_path / "soul_map.json"
    path.write_text(
        json.dumps(
            {
                "adversarial_state": {
                    "council_weights": {
                        "quant": 1.0,
                        "hype": 1.0,
                        "dark_horse": 1.0,
                        "technical": 1.0,
                    }
                },
                "expert_weights": {
                    "quant": 1.0,
                    "hype": 1.0,
                    "dark_horse": 1.0,
                    "technical": 1.0,
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(council_weights, "SOUL_MAP_PATH", str(path))
    monkeypatch.setenv("SOUL_MAP_PATH", str(path))
    return path


def _hold_writers(path: str, stop: threading.Event) -> None:
    lock = soul_map_io._lock_for(path + ".writers")
    lock.acquire()
    try:
        stop.wait(30)
    finally:
        lock.release()


def test_indicator_scheduler_reschedules_after_lock_timeout(tmp_path, monkeypatch):
    soul = tmp_path / "soul_map.json"
    soul.write_text("{}", encoding="utf-8")
    reg = tmp_path / "registry.json"
    reg.write_text(
        json.dumps(
            {
                "1": {
                    "emission": 2.0,
                    "social_mentions": 2000,
                    "is_overvalued": False,
                    "status": "active",
                }
            }
        ),
        encoding="utf-8",
    )
    pairs = tmp_path / "price_pairs.json"
    pairs.write_text(json.dumps({"1": {"symbol": "SN1"}}), encoding="utf-8")

    scheduled: List[float] = []
    monkeypatch.setattr(
        indicator_scheduler,
        "schedule_in_seconds",
        lambda _job, _fn, seconds: scheduled.append(seconds),
    )
    monkeypatch.setattr(soul_map_io, "_SOUL_MAP_LOCK_DEADLINE_SECONDS", 0.05)

    stop = threading.Event()
    holder = threading.Thread(
        target=_hold_writers,
        args=(str(soul), stop),
        daemon=True,
    )
    holder.start()

    indicator_scheduler.stop_indicator_scheduler()
    with indicator_scheduler._scheduler_lock:
        sched = indicator_scheduler.IndicatorScheduler(
            refresh_minutes=15,
            soul_map_path=str(soul),
            registry_path=str(reg),
        )
        indicator_scheduler._scheduler = sched
        sched.liveness.start()

    try:
        sched._tick()
    finally:
        stop.set()
        holder.join(timeout=5)

    assert scheduled, "scheduler must reschedule after soul-map lock timeout on persist"


def test_indicator_scheduler_reschedules_when_cycle_or_liveness_raises(
    tmp_path, monkeypatch
):
    soul = tmp_path / "soul_map.json"
    soul.write_text("{}", encoding="utf-8")
    scheduled: List[float] = []
    monkeypatch.setattr(
        indicator_scheduler,
        "schedule_in_seconds",
        lambda _job, _fn, seconds: scheduled.append(seconds),
    )

    class BoomEngine:
        def run_cycle(self):
            return {"subnets_processed": 1, "signals_emitted": 0}

    indicator_scheduler.stop_indicator_scheduler()
    with indicator_scheduler._scheduler_lock:
        sched = indicator_scheduler.IndicatorScheduler(
            refresh_minutes=15,
            soul_map_path=str(soul),
            engine_factory=lambda: BoomEngine(),
        )
        indicator_scheduler._scheduler = sched
        sched.liveness.start()

    def _boom(**_kwargs):
        raise RuntimeError("liveness write failed")

    monkeypatch.setattr(sched.liveness, "record_success", _boom)

    result = sched._tick()
    assert result.get("ok") is True
    assert scheduled, "tick must reschedule even when liveness raises"


@pytest.mark.parametrize("corrupt", [b"", b"\xff\xfe", b'{"a": 1}'], ids=["empty", "utf16", "object"])
def test_postmortem_corrupt_files_do_not_abort_resolution(
    pm_dir, portfolio_path, corrupt, monkeypatch
):
    monkeypatch.setattr("internal.judges.weights.nudge_judge", lambda *_a, **_k: None)
    oracle_path = pm_dir / "oracle.json"
    oracle_path.write_bytes(corrupt)

    prediction = dict(PREDICTION)
    for judge in tracker.all_judges():
        judge.open_position(prediction, size=1.0)

    summary = tracker.on_prediction_resolved(prediction)
    assert set(summary["judges"]) == {"oracle", "echo", "pulse"}
    for name in ("oracle", "echo", "pulse"):
        assert summary["judges"][name]["closed"] is not None, name

    assert oracle_path.read_bytes() == corrupt
    for name in ("echo", "pulse"):
        rows = postmortems.list_for_judge(name)
        assert len(rows) == 1, name
        assert rows[0]["prediction_id"] == prediction["id"]

    oracle_block = summary["judges"]["oracle"]
    assert oracle_block.get("postmortem") is None
    assert oracle_block.get("postmortem_error")


@pytest.mark.parametrize("corrupt", [b"", b"\xff\xfe"], ids=["empty", "utf16"])
@pytest.mark.parametrize(
    "route",
    [
        "/api/postmortems/oracle",
        "/api/postmortems?judge=oracle",
        "/api/judges/oracle/postmortems",
        "/api/postmortems",
    ],
)
def test_postmortem_routes_return_200_with_unavailable_on_corrupt_file(
    pm_dir, corrupt, route, monkeypatch
):
    client = TestClient(app)
    oracle_path = pm_dir / "oracle.json"
    oracle_path.write_bytes(corrupt)
    valid = {
        "prediction_id": "keep-echo",
        "judge": "echo",
        "created_at": "2026-01-01T00:00:00Z",
    }
    (pm_dir / "echo.json").write_text(json.dumps([valid]), encoding="utf-8")

    response = client.get(route)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body.get("unavailable") == ["oracle"]
    if route == "/api/postmortems":
        assert body["postmortems"]["echo"] == [valid]
    else:
        assert body.get("postmortems") == []
    assert oracle_path.read_bytes() == corrupt


@pytest.fixture
def client():
    return TestClient(app)


def test_postmortem_routes_symlink_escape_still_404(tmp_path, monkeypatch, client):
    data_dir = tmp_path / "data"
    postmortems_dir = data_dir / "postmortems"
    postmortems_dir.mkdir(parents=True)
    outside = data_dir / "outside.json"
    outside.write_text(json.dumps([{"secret": "symlink-leak"}]), encoding="utf-8")
    (postmortems_dir / "oracle.json").symlink_to(outside)
    monkeypatch.setattr(postmortems, "POSTMORTEMS_DIR", str(postmortems_dir))

    response = client.get("/api/postmortems/oracle")
    assert response.status_code == 404


def test_postmortem_save_fsyncs(pm_dir, monkeypatch):
    fsync_calls: List[int] = []
    dir_fsyncs: List[str] = []
    real_fsync = os.fsync

    def _tracking_fsync(fd: int) -> None:
        fsync_calls.append(fd)
        real_fsync(fd)

    import internal.file_utils as file_utils

    real_dir_fsync = file_utils._fsync_dir

    def _track_dir(path: str) -> None:
        dir_fsyncs.append(path)
        real_dir_fsync(path)

    monkeypatch.setattr(os, "fsync", _tracking_fsync)
    monkeypatch.setattr(file_utils, "_fsync_dir", _track_dir)

    postmortems.record("oracle", PREDICTION, actual_pct=-1.0)
    assert fsync_calls, "postmortem save must fsync the tmp file"
    assert dir_fsyncs, "postmortem save must fsync the directory"


def test_fire_weights_refused_save_is_fire_error(soul_path, monkeypatch):
    monkeypatch.setattr(soul_map_io, "_SOUL_MAP_LOCK_DEADLINE_SECONDS", 0.05)
    stop = threading.Event()
    holder = threading.Thread(
        target=_hold_writers,
        args=(str(soul_path), stop),
        daemon=True,
    )
    holder.start()
    try:
        proposed = {"quant": 1.5, "hype": 0.8, "dark_horse": 0.9, "technical": 1.0}
        with pytest.raises(FireError) as exc:
            cal.fire_weights(proposed, soul_map_path=str(soul_path))
        assert str(exc.value) == "save_refused"
        assert exc.value.rollback_status == "not_needed"
    finally:
        stop.set()
        holder.join(timeout=5)


def test_fire_weights_initial_save_conflict_is_fire_error(soul_path, monkeypatch):
    proposed = {"quant": 1.5, "hype": 0.8, "dark_horse": 0.9, "technical": 1.0}
    stale_backup = dict(council_weights.load_weights(str(soul_path)))
    real_load = council_weights.load_weights

    def _race_load(path=council_weights.SOUL_MAP_PATH):
        if not getattr(_race_load, "primed", False):
            _race_load.primed = True
            council_weights.nudge_expert("quant", True, str(soul_path))
            return stale_backup
        return real_load(path)

    monkeypatch.setattr(cal, "load_weights", _race_load)
    with pytest.raises(FireError) as exc:
        cal.fire_weights(proposed, soul_map_path=str(soul_path))
    assert str(exc.value) == "save_conflict"
    assert exc.value.rollback_status == "not_needed"


def _stub_fire_rollback(
    monkeypatch,
    *,
    rollback_raises: Any = None,
    rollback_ok: bool = True,
):
    backup = {"quant": 1.0, "hype": 1.0, "dark_horse": 1.0, "technical": 1.0}
    proposed = {"quant": 1.5, "hype": 0.8, "dark_horse": 0.9, "technical": 1.0}
    calls = {"n": 0}
    real_save = council_weights.save_weights

    state = {"inject_mismatch": False, "in_fire": False}

    def _save(weights, path, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            saved = real_save(weights, path, **kwargs)
            state["inject_mismatch"] = True
            return saved
        if rollback_raises is not None:
            raise rollback_raises
        return rollback_ok

    real_load = council_weights.load_weights

    def _load(path=council_weights.SOUL_MAP_PATH):
        data = real_load(path)
        if state["in_fire"] and state["inject_mismatch"]:
            data = dict(data)
            data["quant"] = 9.9
        return data

    real_fire = cal.fire_weights

    def _fire_wrapper(*args, **kwargs):
        state["in_fire"] = True
        try:
            return real_fire(*args, **kwargs)
        finally:
            state["in_fire"] = False

    monkeypatch.setattr(cal, "load_weights", _load)
    monkeypatch.setattr(cal, "save_weights", _save)
    monkeypatch.setattr(cal, "fire_weights", _fire_wrapper)
    return proposed


def _write_predictions(path: Path, n: int = 35) -> None:
    rows = [
        {
            "id": f"p-{i}",
            "expert": "quant",
            "status": "resolved",
            "outcome": "hit",
            "correct": True,
            "actual_pct": 2.0,
            "predicted_pct": 1.0,
            "direction": "up",
            "reference_price": 100.0,
            "resolved_price": 102.0,
            "created_at": f"2026-07-01T12:{i:02d}:00Z",
            "resolved_at": f"2026-07-01T13:{i:02d}:00Z",
        }
        for i in range(n)
    ]
    path.write_text(
        json.dumps({"predictions": [], "resolved": rows, "stats": {}}),
        encoding="utf-8",
    )


@pytest.mark.parametrize(
    "mode,expected_msg,expected_status",
    [
        ("conflict", "rollback_conflict", "conflict"),
        ("refused", "rollback_refused", "refused"),
    ],
)
def test_fire_weights_rollback_conflict_and_refused_record_live_weights(
    soul_path, monkeypatch, mode, expected_msg, expected_status
):
    if mode == "conflict":
        _stub_fire_rollback(
            monkeypatch,
            rollback_raises=council_weights.ConcurrentWeightUpdate("stale"),
        )
    else:
        _stub_fire_rollback(monkeypatch, rollback_ok=False)

    pred_path = Path(soul_path).parent / "predictions.json"
    _write_predictions(pred_path)

    result = cal.run_calibration_pipeline(
        force=True,
        soul_map_path=str(soul_path),
        predictions_path=str(pred_path),
    )
    assert result["status"] == "fire_failed"
    assert result.get("rollback_status") == expected_status
    disk = council_weights.load_weights(str(soul_path))
    assert result.get("weights_after_failure") == disk
    assert disk["quant"] != 9.9
    status = cal.get_calibration_status(
        soul_map_path=str(soul_path),
        predictions_path=str(pred_path),
    )
    assert status["calibration"].get("last_error") == expected_msg
    assert status["calibration"].get("rollback_status") == expected_status


def test_simivision_persist_lock_timeout_still_returns_signals(tmp_path, monkeypatch):
    from internal.simivision import engine as simi_engine

    soul = tmp_path / "soul_map.json"
    soul.write_text("{}", encoding="utf-8")
    reg = {
        "7": {
            "emission": 0.5,
            "social_mentions": 50,
            "is_overvalued": False,
            "emission_rank": 20,
            "updated_at": "2026-01-01T00:00:00Z",
        }
    }

    def _lock_timeout(*_a, **_k):
        raise SoulMapLockWaitTimeout("held")

    monkeypatch.setattr(simi_engine, "write_soul_map", _lock_timeout)
    signals = simi_engine.generate_signals(registry=reg, top_n=5, soul_map_path=str(soul))
    assert signals
    assert signals[0]["netuid"] == 7


def test_rebalance_script_exits_nonzero_on_refused_save(soul_path, monkeypatch):
    repo = Path(__file__).resolve().parents[1]
    monkeypatch.setattr(soul_map_io, "_SOUL_MAP_LOCK_DEADLINE_SECONDS", 0.05)
    stop = threading.Event()
    holder = threading.Thread(
        target=_hold_writers,
        args=(str(soul_path), stop),
        daemon=True,
    )
    holder.start()
    try:
        proc = subprocess.run(
            [sys.executable, "scripts/rebalance_expert_weights.py", "--save"],
            cwd=str(repo),
            env={**os.environ, "SOUL_MAP_PATH": str(soul_path)},
            capture_output=True,
            text=True,
        )
        assert proc.returncode != 0
        assert "[saved]" not in proc.stdout
    finally:
        stop.set()
        holder.join(timeout=5)