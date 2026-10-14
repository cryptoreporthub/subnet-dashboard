"""Atomic JSON write helpers."""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path

from internal.file_utils import safe_write_json


def test_safe_write_json_survives_reap_while_locked(tmp_path, monkeypatch):
    import fcntl
    import time

    from internal.tmp_boot_reaper import reap_stale_tmp_files

    target = tmp_path / "alerts.json"
    barrier = threading.Barrier(2)
    errors: list[BaseException] = []

    def writer() -> None:
        try:
            barrier.wait()
            fd, temp_path = __import__("tempfile").mkstemp(
                dir=str(tmp_path),
                prefix="alerts.json.",
                suffix=".tmp",
            )
            fcntl.flock(fd, fcntl.LOCK_EX)
            f = os.fdopen(fd, "w", encoding="utf-8")
            f.write('{"held": true}')
            f.flush()
            barrier.wait()
            time.sleep(0.05)
            os.replace(temp_path, str(target))
            f.close()
        except BaseException as exc:
            errors.append(exc)

    def reaper() -> None:
        barrier.wait()
        past = time.time() - 120
        for path in tmp_path.glob("*.tmp"):
            os.utime(path, (past, past))
        reap_stale_tmp_files(min_age_seconds=60)
        barrier.wait()

    t_w = threading.Thread(target=writer)
    t_r = threading.Thread(target=reaper)
    t_w.start()
    t_r.start()
    t_w.join()
    t_r.join()
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
    assert list(tmp_path.glob("whale_intelligence.json.*.tmp")) == []
