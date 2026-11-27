"""Deploy blocker regressions (#1629): scheduler, postmortems, retrain fire, SimiVision."""

from __future__ import annotations

import fcntl
import json
import logging
import os
import stat
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
from internal.store.soul_map_io import WriteOutcome, WriteResult
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

PROPOSED = {"quant": 1.5, "hype": 0.8, "dark_horse": 0.9, "technical": 1.0}


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
                        "quant": 1.4,
                        "hype": 1.0,
                        "dark_horse": 1.0,
                        "technical": 1.0,
                    }
                },
                "expert_weights": {
                    "quant": 1.4,
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


@pytest.fixture
def scheduler_cleanup():
    yield
    indicator_scheduler.stop_indicator_scheduler()
    with indicator_scheduler._scheduler_lock:
        indicator_scheduler._scheduler = None


class _StubEngine:
    def run_cycle(self):
        return {"subnets_processed": 1, "signals_emitted": 0}


class _BoomEngine:
    def run_cycle(self):
        raise RuntimeError("cycle failed")


def _hold_writers(path: str, stop: threading.Event) -> None:
    lock = soul_map_io._lock_for(path + ".writers")
    lock.acquire()
    try:
        stop.wait(30)
    finally:
        lock.release()


def _register_scheduler(soul, monkeypatch, engine_factory):
    scheduled: List[float] = []
    monkeypatch.setattr(
        indicator_scheduler,
        "schedule_in_seconds",
        lambda _job, _fn, seconds: scheduled.append(seconds),
    )
    indicator_scheduler.stop_indicator_scheduler()
    with indicator_scheduler._scheduler_lock:
        sched = indicator_scheduler.IndicatorScheduler(
            refresh_minutes=15,
            soul_map_path=str(soul),
            engine_factory=engine_factory,
        )
        indicator_scheduler._scheduler = sched
        sched.liveness.start()
    return sched, scheduled


def test_indicator_scheduler_reschedules_after_lock_timeout(
    tmp_path, monkeypatch, scheduler_cleanup
):
    soul = tmp_path / "soul_map.json"
    soul.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(soul_map_io, "_SOUL_MAP_LOCK_DEADLINE_SECONDS", 0.05)

    stop = threading.Event()
    holder = threading.Thread(
        target=_hold_writers,
        args=(str(soul), stop),
        daemon=True,
    )
    holder.start()
    sched, scheduled = _register_scheduler(soul, monkeypatch, lambda: _StubEngine())
    try:
        result = sched._tick()
    finally:
        stop.set()
        holder.join(timeout=5)

    assert result["ok"] is True
    assert sched._consecutive_failures == 0
    assert scheduled == [15 * 60]


def test_indicator_scheduler_reschedules_when_liveness_raises(
    tmp_path, monkeypatch, scheduler_cleanup
):
    soul = tmp_path / "soul_map.json"
    soul.write_text("{}", encoding="utf-8")
    sched, scheduled = _register_scheduler(soul, monkeypatch, lambda: _StubEngine())

    def _boom(**_kwargs):
        raise RuntimeError("liveness write failed")

    monkeypatch.setattr(sched.liveness, "record_success", _boom)

    result = sched._tick()
    assert result.get("ok") is True
    assert sched._consecutive_failures == 0
    assert sched._backoff_minutes == 15
    assert scheduled == [15 * 60]


def test_indicator_scheduler_reschedules_when_cycle_raises(
    tmp_path, monkeypatch, scheduler_cleanup
):
    soul = tmp_path / "soul_map.json"
    soul.write_text("{}", encoding="utf-8")
    sched, scheduled = _register_scheduler(soul, monkeypatch, lambda: _BoomEngine())

    result = sched._tick()
    assert result.get("ok") is False
    assert sched._consecutive_failures == 1
    assert sched._backoff_minutes == 30
    assert scheduled == [30 * 60]


def test_indicator_scheduler_reschedules_when_refresh_cycle_raises(
    tmp_path, monkeypatch, scheduler_cleanup
):
    soul = tmp_path / "soul_map.json"
    soul.write_text("{}", encoding="utf-8")
    sched, scheduled = _register_scheduler(soul, monkeypatch, lambda: _StubEngine())

    def _boom(*_a, **_k):
        raise RuntimeError("refresh exploded")

    monkeypatch.setattr(sched, "_run_refresh_cycle", _boom)
    result = sched._tick()
    assert result.get("ok") is False
    assert result.get("error") == "refresh exploded"
    assert sched._consecutive_failures == 1
    assert scheduled == [30 * 60]


@pytest.mark.parametrize("corrupt", [b"", b"\xff\xfe", b'{"a": 1}'], ids=["empty", "utf16", "object"])
def test_postmortem_corrupt_files_do_not_abort_resolution(
    pm_dir, portfolio_path, corrupt, monkeypatch, caplog
):
    monkeypatch.setattr("internal.judges.weights.nudge_judge", lambda *_a, **_k: None)
    oracle_path = pm_dir / "oracle.json"
    oracle_path.write_bytes(corrupt)

    prediction = dict(PREDICTION)
    for judge in tracker.all_judges():
        judge.open_position(prediction, size=1.0)

    def _boom(*_a, **_k):
        raise RuntimeError("trail down")

    monkeypatch.setattr("internal.learning.trail_events.emit_trail_event", _boom)
    with caplog.at_level(logging.ERROR):
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
    assert any("postmortem skipped" in r.getMessage() for r in caplog.records)
    assert any("postmortem_skipped trail emit failed" in r.getMessage() for r in caplog.records)
    assert any(
        r.levelno >= logging.ERROR and "postmortem_skipped trail emit failed" in r.getMessage()
        for r in caplog.records
    )


def test_postmortem_lock_timeout_does_not_abort_resolution(
    pm_dir, portfolio_path, monkeypatch
):
    monkeypatch.setattr("internal.judges.weights.nudge_judge", lambda *_a, **_k: None)
    monkeypatch.setattr(postmortems, "POSTMORTEM_LOCK_TIMEOUT_SECONDS", 0.05)
    lock_path = pm_dir / "oracle.json.lock"
    holder = open(lock_path, "a+", encoding="utf-8")
    fcntl.flock(holder.fileno(), fcntl.LOCK_EX)
    try:
        prediction = dict(PREDICTION)
        for judge in tracker.all_judges():
            judge.open_position(prediction, size=1.0)
        summary = tracker.on_prediction_resolved(prediction)
    finally:
        fcntl.flock(holder.fileno(), fcntl.LOCK_UN)
        holder.close()

    assert set(summary["judges"]) == {"oracle", "echo", "pulse"}
    for name in ("oracle", "echo", "pulse"):
        assert summary["judges"][name]["closed"] is not None, name
    assert summary["judges"]["oracle"].get("postmortem") is None
    assert summary["judges"]["oracle"].get("postmortem_error") == "PostmortemLockTimeout"
    for name in ("echo", "pulse"):
        rows = postmortems.list_for_judge(name)
        assert len(rows) == 1, name


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
    events: List[tuple] = []
    real_fsync = os.fsync
    real_replace = os.replace
    import internal.file_utils as file_utils

    real_dir_fsync = file_utils._fsync_dir

    def _tracking_fsync(fd: int) -> None:
        mode = os.fstat(fd).st_mode
        if stat.S_ISREG(mode):
            events.append(("tmp_fsync", fd, True))
        real_fsync(fd)

    def _tracking_replace(src, dst):
        events.append(("replace", src, dst))
        real_replace(src, dst)

    def _track_dir(path: str) -> None:
        events.append(("dir_fsync", path))
        real_dir_fsync(path)

    monkeypatch.setattr(os, "fsync", _tracking_fsync)
    monkeypatch.setattr(postmortems.os, "replace", _tracking_replace)
    monkeypatch.setattr(file_utils, "_fsync_dir", _track_dir)

    postmortems.record("oracle", PREDICTION, actual_pct=-1.0)
    kinds = [e[0] for e in events]
    assert kinds == ["tmp_fsync", "replace", "dir_fsync"]
    assert events[0][2] is True


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
        with pytest.raises(FireError) as exc:
            cal.fire_weights(PROPOSED, soul_map_path=str(soul_path))
        assert str(exc.value) == "save_refused"
        assert exc.value.rollback_status == "not_needed"
    finally:
        stop.set()
        holder.join(timeout=5)


def test_fire_weights_initial_save_conflict_is_fire_error(soul_path, monkeypatch):
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
        cal.fire_weights(PROPOSED, soul_map_path=str(soul_path))
    assert str(exc.value) == "save_conflict"
    assert exc.value.rollback_status == "not_needed"


def test_fire_weights_backup_read_conflict_is_fire_error(soul_path, monkeypatch):
    saves: List[Any] = []

    def _load(_path=None):
        raise council_weights.ConcurrentWeightUpdate("stale")

    monkeypatch.setattr(cal, "load_weights", _load)
    monkeypatch.setattr(cal, "save_weights", lambda *_a, **_k: saves.append(1) or True)
    with pytest.raises(FireError) as exc:
        cal.fire_weights(PROPOSED, soul_map_path=str(soul_path))
    assert str(exc.value) == "load_conflict"
    assert exc.value.rollback_status == "not_needed"
    assert saves == []


def test_fire_weights_verify_read_conflict_is_fire_error(soul_path, monkeypatch):
    calls = {"n": 0}
    real_load = council_weights.load_weights

    def _load(path=council_weights.SOUL_MAP_PATH):
        calls["n"] += 1
        if calls["n"] == 2:
            raise council_weights.ConcurrentWeightUpdate("stale")
        return real_load(path)

    monkeypatch.setattr(cal, "load_weights", _load)
    with pytest.raises(FireError) as exc:
        cal.fire_weights(PROPOSED, soul_map_path=str(soul_path))
    assert str(exc.value) == "verify_read_conflict"
    assert exc.value.rollback_status == "unknown"


def test_fire_failed_state_persisted_when_post_failure_read_conflicts(
    soul_path, monkeypatch
):
    saved: List[dict] = []
    real_save = cal._save_calibration_state

    def _save(state, soul_map_path=None):
        saved.append(dict(state))
        return real_save(state, soul_map_path=soul_map_path)

    load_calls = {"n": 0}

    def _load(_path=None):
        load_calls["n"] += 1
        if load_calls["n"] >= 2:
            raise council_weights.ConcurrentWeightUpdate("stale")
        return {
            "quant": 1.0,
            "hype": 1.0,
            "dark_horse": 1.0,
            "technical": 1.0,
        }

    def _fire(*_a, **_k):
        raise FireError("rollback_conflict", rollback_status="conflict")

    monkeypatch.setattr(cal, "_save_calibration_state", _save)
    monkeypatch.setattr(cal, "load_weights", _load)
    monkeypatch.setattr(cal, "fire_weights", _fire)
    monkeypatch.setattr(cal, "load_training_rows", lambda *_a, **_k: [{"status": "resolved"}] * 40)
    monkeypatch.setattr(cal, "compute_proposed_weights", lambda *_a, **_k: PROPOSED)
    monkeypatch.setattr(
        cal,
        "certify_weights",
        lambda *_a, **_k: {
            "passed": True,
            "proposed_accuracy": 1.0,
            "current_accuracy": 0.5,
        },
    )

    result = cal.run_calibration_pipeline(soul_map_path=str(soul_path), force=True)
    assert result["status"] == "fire_failed"
    assert saved
    assert saved[0]["last_cert_status"] == "fire_failed"
    assert saved[0]["rollback_status"] == "conflict"
    assert saved[0]["proposed_weights"] == PROPOSED


def test_retrain_backup_read_conflict_releases_lock_and_records_failure(
    soul_path, monkeypatch
):
    monkeypatch.setattr(
        cal,
        "load_weights",
        lambda *_a, **_k: (_ for _ in ()).throw(
            council_weights.ConcurrentWeightUpdate("stale")
        ),
    )
    try:
        result = cal.run_calibration_pipeline(
            dry_run=True, soul_map_path=str(soul_path)
        )
        assert not cal._retrain_lock.locked()
        assert result["status"] == "fire_failed"
        second = cal.run_calibration_pipeline(
            dry_run=True, soul_map_path=str(soul_path)
        )
        assert second.get("status") != "in_progress"
    finally:
        if cal._retrain_lock.locked():
            cal._retrain_in_progress = False
            cal._retrain_lock.release()


def _stub_fire_rollback(
    monkeypatch,
    *,
    rollback_raises: Any = None,
    rollback_ok: bool = True,
):
    real_save = council_weights.save_weights

    state = {"fired_payload": None, "inject_mismatch": False, "in_fire": False}

    def _same(left, right) -> bool:
        if not isinstance(left, dict) or not isinstance(right, dict):
            return False
        keys = set(left) | set(right)
        return all(
            abs(float(left.get(k, 0) or 0) - float(right.get(k, 0) or 0)) < 1e-4
            for k in keys
        )

    def _save(weights, path, expected_weights=None, **kwargs):
        fired = state["fired_payload"]
        if fired is not None and _same(expected_weights, fired):
            if rollback_raises is not None:
                raise rollback_raises
            return rollback_ok
        saved = real_save(weights, path, expected_weights=expected_weights, **kwargs)
        state["fired_payload"] = dict(weights)
        state["inject_mismatch"] = True
        return saved

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
    return PROPOSED


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


def test_calibration_status_returns_200_when_load_weights_conflicts(monkeypatch):
    def _boom(*_a, **_k):
        raise council_weights.ConcurrentWeightUpdate("stale")

    monkeypatch.setattr("internal.council.weights.load_weights", _boom)
    client = TestClient(app)
    resp = client.get("/api/calibration/status")
    assert resp.status_code == 200, resp.text
    assert resp.json().get("weights") is None


def test_simivision_persist_lock_timeout_still_returns_signals(
    tmp_path, monkeypatch, caplog
):
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

    calls: List[dict] = []

    def _lock_timeout(*_a, **kwargs):
        calls.append(kwargs)
        assert kwargs.get("raise_on_lock_timeout") is False
        return WriteResult(WriteOutcome.LOCK_WAIT_FAILED, None, detail="held")

    monkeypatch.setattr(soul_map_io, "write_soul_map", _lock_timeout)
    with caplog.at_level("WARNING"):
        signals = simi_engine.generate_signals(
            registry=reg, top_n=5, soul_map_path=str(soul)
        )
    assert calls, "persist path must invoke write_soul_map"
    assert calls[0].get("raise_on_lock_timeout") is False
    assert signals
    assert signals[0]["netuid"] == 7
    assert "lock_wait_failed" in caplog.text.lower() or "LOCK_WAIT_FAILED" in caplog.text


def test_rebalance_script_exits_nonzero_on_refused_save(soul_path, monkeypatch):
    import importlib.util

    repo = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location(
        "rebalance_expert_weights",
        repo / "scripts" / "rebalance_expert_weights.py",
    )
    rebalance = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(rebalance)

    monkeypatch.setattr(council_weights, "SOUL_MAP_PATH", str(soul_path))
    real_save_weights = council_weights.save_weights
    trail_rows: List[str] = []
    monkeypatch.setattr(
        "internal.learning.trail_bus.emit_weight_change",
        lambda name, **_: trail_rows.append(name),
    )

    argv = ["rebalance_expert_weights.py", "--save"]
    monkeypatch.setattr(rebalance.sys, "argv", argv)
    monkeypatch.setattr(council_weights, "save_weights", lambda *_a, **_k: False)
    assert rebalance.main() == 3
    assert trail_rows == []

    def _conflict(*_a, **_k):
        raise council_weights.ConcurrentWeightUpdate("stale")

    monkeypatch.setattr(council_weights, "save_weights", _conflict)
    assert rebalance.main() == 2
    assert trail_rows == []

    monkeypatch.setattr(council_weights, "save_weights", real_save_weights)
    assert rebalance.main() == 0
    assert "quant" in trail_rows


def test_rebalance_script_exits_nonzero_on_load_conflict(soul_path, monkeypatch):
    import importlib.util

    repo = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location(
        "rebalance_expert_weights",
        repo / "scripts" / "rebalance_expert_weights.py",
    )
    rebalance = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(rebalance)

    monkeypatch.setattr(council_weights, "SOUL_MAP_PATH", str(soul_path))
    saves: List[int] = []
    trail_rows: List[str] = []
    monkeypatch.setattr(
        "internal.learning.trail_bus.emit_weight_change",
        lambda name, **_: trail_rows.append(name),
    )
    monkeypatch.setattr(
        council_weights,
        "load_weights",
        lambda *_a, **_k: (_ for _ in ()).throw(
            council_weights.ConcurrentWeightUpdate("stale")
        ),
    )
    monkeypatch.setattr(
        council_weights, "save_weights", lambda *_a, **_k: saves.append(1) or True
    )
    monkeypatch.setattr(rebalance.sys, "argv", ["rebalance_expert_weights.py", "--save"])
    assert rebalance.main() == 2
    assert saves == []
    assert trail_rows == []


def test_panel_summary_unavailable_when_all_postmortems_corrupt(
    pm_dir, tmp_path, monkeypatch
):
    from internal.learning import panel_summaries

    for name in ("oracle", "echo", "pulse"):
        (pm_dir / f"{name}.json").write_bytes(b"")
    monkeypatch.setattr(
        "internal.judges.portfolios.PORTFOLIOS_PATH",
        str(tmp_path / "portfolios.json"),
    )
    (tmp_path / "portfolios.json").write_text("{}", encoding="utf-8")
    out = panel_summaries.summarize_judges()
    text = out["text"]
    assert "unavailable" in text.lower()
    assert "No judge post-mortems recorded yet" not in text
