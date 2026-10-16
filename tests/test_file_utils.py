"""Atomic JSON write helpers."""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from internal.file_utils import safe_write_json


def test_safe_write_json_survives_reap_while_dump_blocked(tmp_path, monkeypatch):
    from internal.tmp_boot_reaper import reap_stale_tmp_files

    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    target = tmp_path / "alerts.json"
    gate = threading.Event()
    dump_started = threading.Event()
    real_dump = json.dump

    def slow_dump(*args, **kwargs):
        dump_started.set()
        assert gate.wait(timeout=5)
        return real_dump(*args, **kwargs)

    errors: list[BaseException] = []

    def writer() -> None:
        try:
            with patch("internal.file_utils.json.dump", slow_dump):
                safe_write_json(str(target), {"x": 1})
        except BaseException as exc:
            errors.append(exc)

    t = threading.Thread(target=writer)
    t.start()
    assert dump_started.wait(timeout=5)
    sidecars = list(tmp_path.glob("alerts.json.*.*.tmp"))
    assert len(sidecars) == 1
    past = time.time() - 7200
    os.utime(sidecars[0], (past, past))
    reap_stale_tmp_files(min_age_seconds=0, at_boot=True)
    gate.set()
    t.join(timeout=5)
    assert not errors
    assert target.exists()


def test_safe_write_json_concurrent_writers_do_not_share_temp(tmp_path):
    target = tmp_path / "whale_intelligence.json"
    barrier = threading.Barrier(2)
    errors: list[BaseException] = []

    def writer(key: str, letter: str) -> None:
        try:
            barrier.wait()
            safe_write_json(str(target), {key: letter * 64})
        except BaseException as exc:
            errors.append(exc)

    t_a = threading.Thread(target=writer, args=("a", "A"))
    t_b = threading.Thread(target=writer, args=("b", "B"))
    t_a.start()
    t_b.start()
    t_a.join()
    t_b.join()

    assert not errors
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert set(payload.keys()) == {"a"} or set(payload.keys()) == {"b"}
    assert payload[list(payload.keys())[0]] in ("A" * 64, "B" * 64)
    assert not list(tmp_path.glob("tmp*.json"))
    assert list(tmp_path.glob("whale_intelligence.json.*.*.tmp")) == []


def test_safe_write_json_dead_pid_sidecar_reaped(tmp_path, monkeypatch):
    from internal.tmp_boot_reaper import reap_stale_tmp_files

    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    dead_pid = 999999
    sidecar = tmp_path / f"alerts.json.{dead_pid}.deadbeef.tmp"
    sidecar.write_text("{}", encoding="utf-8")
    count, _ = reap_stale_tmp_files(min_age_seconds=0, at_boot=True)
    assert count >= 1
    assert not sidecar.exists()


def test_safe_write_json_fsyncs_temp_before_replace_then_directory(tmp_path, monkeypatch):
    events: list[str] = []
    real_fsync = os.fsync
    real_replace = os.replace

    def record_fsync(fd):
        events.append("fsync")
        return real_fsync(fd)

    def record_replace(src, dst):
        events.append("replace")
        return real_replace(src, dst)

    monkeypatch.setattr(os, "fsync", record_fsync)
    monkeypatch.setattr(os, "replace", record_replace)
    target = tmp_path / "state.json"
    safe_write_json(str(target), {"x": 1})
    assert events == ["fsync", "replace", "fsync"]
    assert json.loads(target.read_text(encoding="utf-8")) == {"x": 1}


def test_safe_write_json_fsync_failure_keeps_previous_file(tmp_path, monkeypatch):
    target = tmp_path / "state.json"
    target.write_text('{"old": true}', encoding="utf-8")

    def failing_fsync(fd):
        raise OSError("EIO")

    monkeypatch.setattr(os, "fsync", failing_fsync)
    with pytest.raises(OSError):
        safe_write_json(str(target), {"new": 1})
    assert json.loads(target.read_text(encoding="utf-8")) == {"old": True}
    assert list(tmp_path.glob("state.json.*.*.tmp")) == []


def test_safe_write_json_dir_fsync_failure_still_commits(tmp_path, monkeypatch):
    target = tmp_path / "state.json"
    real_fsync = os.fsync
    calls = 0

    def fsync_maybe_fail(fd):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("dir EIO")
        return real_fsync(fd)

    monkeypatch.setattr(os, "fsync", fsync_maybe_fail)
    safe_write_json(str(target), {"new": 1})
    assert json.loads(target.read_text(encoding="utf-8")) == {"new": 1}
    assert calls == 2


def test_safe_write_json_compact_separators(tmp_path):
    target = tmp_path / "state.json"
    safe_write_json(str(target), {"a": 1}, indent=None, separators=(",", ":"))
    assert target.read_text(encoding="utf-8") == '{"a":1}'
