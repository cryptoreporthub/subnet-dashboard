"""Atomic JSON write helpers."""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from unittest.mock import patch

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
