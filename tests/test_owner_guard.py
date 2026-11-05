"""Single-writer step 1: owner lock + volume marker (fail-closed writes)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap

import pytest

import internal.owner_guard as og


def test_second_process_cannot_acquire_lock_while_first_holds(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setenv("DATA_DIR", str(data))
    og.reset_owner_guard_for_tests()

    ok1, _ = og.try_acquire_write_owner_lock()
    assert ok1 is True

    holder = textwrap.dedent(
        f"""
        import os, time
        os.environ["DATA_DIR"] = {str(data)!r}
        from internal.owner_guard import try_acquire_write_owner_lock
        ok, detail = try_acquire_write_owner_lock()
        print(f"{{ok}}|{{detail}}")
        if ok:
            time.sleep(3)
        """
    )
    proc = subprocess.Popen(
        [sys.executable, "-c", holder],
        cwd=os.getcwd(),
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        stdout, _ = proc.communicate(timeout=10)
    finally:
        if proc.poll() is None:
            proc.kill()
    line = stdout.strip().splitlines()[-1]
    ok2_s, detail = line.split("|", 1)
    assert ok2_s == "False"
    assert detail == "write_owner_lock_contended"


def test_missing_volume_marker_refuses_write_prod_like(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setenv("DATA_DIR", str(data))
    monkeypatch.setenv("DATA_DIR_IS_VOLUME", "on")
    og.reset_owner_guard_for_tests()

    ok, _ = og.try_acquire_write_owner_lock()
    assert ok is True
    assert og.owner_guard_reason() == "volume_marker_missing"
    with pytest.raises(og.WriteRefused, match="volume_marker_missing"):
        og.owner_guard(operation="test_persist")


def test_wrong_volume_marker_refuses_write(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    marker = data / og.VOLUME_MARKER_NAME
    marker.write_text(json.dumps({"version": 1, "fingerprint": "wrong:999"}) + "\n")
    monkeypatch.setenv("DATA_DIR", str(data))
    monkeypatch.setenv("DATA_DIR_IS_VOLUME", "on")
    og.reset_owner_guard_for_tests()

    ok, _ = og.try_acquire_write_owner_lock()
    assert ok is True
    assert og.owner_guard_reason() == "volume_marker_fingerprint_mismatch"
    with pytest.raises(og.WriteRefused):
        og.owner_guard()


def test_reads_unaffected_without_owner_guard(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    soul = data / "soul_map.json"
    soul.write_text('{"x": 1}\n')
    monkeypatch.setenv("DATA_DIR", str(data))
    monkeypatch.setenv("DATA_DIR_IS_VOLUME", "on")
    og.reset_owner_guard_for_tests()
    og.try_acquire_write_owner_lock()

    from internal.store.soul_map_io import read_soul_map

    assert read_soul_map(str(soul)) == {"x": 1}


def test_lock_released_after_process_exit(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    script = textwrap.dedent(
        f"""
        import os
        os.environ["DATA_DIR"] = {str(data)!r}
        from internal.owner_guard import try_acquire_write_owner_lock
        ok, _ = try_acquire_write_owner_lock()
        assert ok
        """
    )
    subprocess.run([sys.executable, "-c", script], check=True, cwd=os.getcwd())

    og.reset_owner_guard_for_tests()
    os.environ["DATA_DIR"] = str(data)
    ok, _ = og.try_acquire_write_owner_lock()
    assert ok is True


def test_owner_guard_skip_blocked_in_prod_like(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setenv("DATA_DIR", str(data))
    monkeypatch.setenv("DATA_DIR_IS_VOLUME", "on")
    monkeypatch.setenv("OWNER_GUARD_SKIP", "on")
    og.reset_owner_guard_for_tests()

    ok, _ = og.try_acquire_write_owner_lock()
    assert ok is True
    assert og.volume_check_prod_like() is True
    assert og.owner_guard_reason() == "volume_marker_missing"


def test_dev_creates_volume_marker_when_not_prod_like(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setenv("DATA_DIR", str(data))
    monkeypatch.delenv("DATA_DIR_IS_VOLUME", raising=False)
    og.reset_owner_guard_for_tests()

    ok, _ = og.try_acquire_write_owner_lock()
    assert ok is True
    assert og.owner_guard_reason() is None
    marker = json.loads((data / og.VOLUME_MARKER_NAME).read_text())
    assert marker["fingerprint"] == og.data_dir_fingerprint()
