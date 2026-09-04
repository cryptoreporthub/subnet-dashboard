"""Patch D mutation-log field coverage. Fast, no network."""

from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path

import pytest

REQUIRED = {
    "abandoned",
    "cycle_generation",
    "operation",
    "path",
    "process_generation",
    "reason",
    "resolver_cycle_id",
    "thread_id",
    "thread_name",
    "trigger",
    "ts_utc",
    "writer_function",
}


def _payloads(caplog, prefix: str = "patchd_mutation"):
    out = []
    for rec in caplog.records:
        msg = rec.getMessage()
        if not msg.startswith(prefix + " "):
            continue
        out.append(json.loads(msg[len(prefix) + 1 :]))
    return out


def _assert_required(payload: dict) -> None:
    missing = REQUIRED - payload.keys()
    assert not missing, missing
    assert payload["ts_utc"].endswith("Z")
    assert payload["thread_id"]
    assert payload["thread_name"]
    assert payload["process_generation"]


def test_save_predictions_emits_atomic_ops(tmp_path, monkeypatch, caplog):
    from internal.learning import predictions_store

    path = tmp_path / "predictions.json"
    lock = tmp_path / "predictions.json.lock"
    monkeypatch.setattr(predictions_store, "PREDICTIONS_PATH", str(path))
    monkeypatch.setattr(predictions_store, "PREDICTIONS_LOCK_PATH", str(lock))
    caplog.set_level(logging.INFO, logger="internal.ops.mutation_log")

    predictions_store.save_predictions(predictions_store._default_data())

    payloads = _payloads(caplog)
    ops = [p["operation"] for p in payloads]
    assert ops == ["start", "temp-write", "rename", "completed"]
    for p in payloads:
        _assert_required(p)
        assert p["path"] == str(path)
        assert p["writer_function"] == "save_predictions"
        assert p["trigger"] == "save_predictions"
        assert p["reason"] == "save_predictions"
    assert path.is_file()


def test_append_prediction_writer_function(tmp_path, monkeypatch, caplog):
    from internal.learning import predictions_store

    path = tmp_path / "predictions.json"
    lock = tmp_path / "predictions.json.lock"
    monkeypatch.setattr(predictions_store, "PREDICTIONS_PATH", str(path))
    monkeypatch.setattr(predictions_store, "PREDICTIONS_LOCK_PATH", str(lock))
    caplog.set_level(logging.INFO, logger="internal.ops.mutation_log")

    ok = predictions_store.append_prediction(
        {
            "id": "p1",
            "netuid": 1,
            "horizon_type": "hour",
            "status": "pending",
            "created_at": "2026-09-04T00:00:00Z",
        }
    )
    assert ok is True
    payloads = _payloads(caplog)
    assert payloads
    assert all(p["writer_function"] == "append_prediction" for p in payloads)
    assert "completed" in [p["operation"] for p in payloads]


def test_write_scheduler_state_emits_atomic_ops(tmp_path, monkeypatch, caplog):
    from internal.council import pick_scheduler

    path = tmp_path / "pick_scheduler_state.json"
    monkeypatch.setattr(pick_scheduler, "PICK_SCHEDULER_STATE_PATH", str(path))
    monkeypatch.setattr(pick_scheduler, "get_pick_scheduler_state", lambda: {"ok": True})
    caplog.set_level(logging.INFO, logger="internal.ops.mutation_log")

    pick_scheduler._write_scheduler_state({"tick": 1})

    payloads = _payloads(caplog)
    assert [p["operation"] for p in payloads] == [
        "start",
        "temp-write",
        "rename",
        "completed",
    ]
    for p in payloads:
        _assert_required(p)
        assert p["path"] == str(path)
        assert p["writer_function"] == "_write_scheduler_state"
        assert p["trigger"] == "daily_pick_tick"
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert stored["ok"] is True
    assert stored["tick"] == 1


def test_resolver_save_json_start_completed(tmp_path, caplog):
    from internal.council import resolver

    path = tmp_path / "predictions.json"
    caplog.set_level(logging.INFO, logger="internal.ops.mutation_log")
    resolver._save_json(str(path), {"ok": True}, caller="resolver")

    payloads = _payloads(caplog)
    assert [p["operation"] for p in payloads] == ["start", "completed"]
    for p in payloads:
        _assert_required(p)
        assert p["path"] == str(path)
        assert p["writer_function"] == "resolver._save_json"
        assert p["trigger"] == "resolver_save"
        assert p["caller"] == "resolver"


def test_resolver_save_json_failed(tmp_path, monkeypatch, caplog):
    from internal.council import resolver
    from internal import file_utils

    path = tmp_path / "predictions.json"
    caplog.set_level(logging.INFO, logger="internal.ops.mutation_log")

    def _boom(*_a, **_k):
        raise OSError("disk full")

    monkeypatch.setattr(file_utils, "safe_write_json", _boom)
    resolver._save_json(str(path), {"ok": True}, trigger="test_fail")
    ops = [p["operation"] for p in _payloads(caplog)]
    assert ops == ["start", "failed"]
    assert _payloads(caplog)[-1]["trigger"] == "test_fail"


def test_bans_timeout_and_shutdown_call_args_unchanged():
    """Instrumentation must not change timeout defaults or pool.shutdown args."""
    sched = Path("internal/council/resolver_scheduler.py").read_text(encoding="utf-8")
    pick = Path("internal/council/pick_scheduler.py").read_text(encoding="utf-8")
    assert 'os.environ.get("RESOLVER_CYCLE_TIMEOUT_SECONDS", "120")' in sched
    assert 'os.environ.get("DAILY_PICK_TICK_TIMEOUT_SECONDS", "90")' in pick
    assert sched.count("pool.shutdown(wait=False, cancel_futures=True)") == 1
    assert pick.count("pool.shutdown(wait=False, cancel_futures=True)") == 1


def test_lifecycle_helper_emits_timeout_fields(caplog):
    from internal.ops.mutation_log import log_lifecycle

    caplog.set_level(logging.INFO, logger="internal.ops.mutation_log")
    log_lifecycle(
        "timeout",
        trigger="resolver_cycle",
        cycle_generation=3,
        extra={"event": "timeout", "abandoned_live": 1, "wait": False},
    )
    payloads = _payloads(caplog, prefix="patchd_lifecycle")
    assert len(payloads) == 1
    p = payloads[0]
    _assert_required(p)
    assert p["operation"] == "timeout"
    assert p["event"] == "timeout"
    assert p["cycle_generation"] == 3
    assert p["abandoned_live"] == 1
    assert p["wait"] is False


def test_direct_writer_resolver_cycle_id_is_json_null(tmp_path, monkeypatch, caplog):
    """Direct save_predictions is not in a resolver cycle — field is null, not omitted."""
    from internal.learning import predictions_store

    path = tmp_path / "predictions.json"
    lock = tmp_path / "predictions.json.lock"
    monkeypatch.setattr(predictions_store, "PREDICTIONS_PATH", str(path))
    monkeypatch.setattr(predictions_store, "PREDICTIONS_LOCK_PATH", str(lock))
    caplog.set_level(logging.INFO, logger="internal.ops.mutation_log")
    predictions_store.save_predictions(predictions_store._default_data())
    for payload in _payloads(caplog):
        assert "resolver_cycle_id" in payload
        assert payload["resolver_cycle_id"] is None


def test_bind_inside_executor_survives_parent_gen_bump(tmp_path, caplog):
    """Simulates _run_cycle: bind on the worker after parent generation already moved."""
    from concurrent.futures import ThreadPoolExecutor

    from internal.council import resolver
    from internal.ops.mutation_log import bind_patchd_context, reset_patchd_context

    parent_ident = threading.get_ident()
    path = tmp_path / "predictions.json"
    caplog.set_level(logging.INFO, logger="internal.ops.mutation_log")
    submitted_gen = 7
    cycle_id = f"{os.getpid()}:{submitted_gen}:2026-09-04T00:00:00Z"

    def _run_cycle():
        token = bind_patchd_context(
            cycle_generation=submitted_gen,
            resolver_cycle_id=cycle_id,
            trigger="resolver_cycle",
        )
        try:
            resolver._save_json(str(path), {"ok": True}, caller="resolver")
            return threading.get_ident()
        finally:
            reset_patchd_context(token)

    with ThreadPoolExecutor(max_workers=1) as pool:
        worker_ident = pool.submit(_run_cycle).result(timeout=5)

    assert worker_ident != parent_ident
    writes = [
        p
        for p in _payloads(caplog)
        if p.get("writer_function") == "resolver._save_json"
    ]
    assert writes
    for payload in writes:
        assert payload["cycle_generation"] == submitted_gen
        assert payload["resolver_cycle_id"] == cycle_id
        assert payload["thread_id"] == worker_ident
