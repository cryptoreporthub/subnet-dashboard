"""Single-writer step 1: owner lock + volume marker (fail-closed writes)."""

from __future__ import annotations

import errno
import json
import os
import subprocess
import sys
import textwrap
import threading

import pytest

import internal.owner_guard as og


@pytest.fixture
def isolated_data_dir(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setenv("DATA_DIR", str(data))
    og.reset_owner_guard_for_tests()
    yield data
    og.reset_owner_guard_for_tests()


def test_second_process_cannot_acquire_lock_while_first_holds(isolated_data_dir):
    data = isolated_data_dir

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


def test_missing_volume_marker_refuses_write_prod_like(isolated_data_dir, monkeypatch):
    monkeypatch.setenv("DATA_DIR_IS_VOLUME", "on")

    ok, detail = og.try_acquire_write_owner_lock()
    assert ok is False
    assert detail == "volume_marker_missing"
    assert og.owner_guard_reason() == "volume_marker_missing"
    with pytest.raises(og.WriteRefused, match="volume_marker_missing"):
        og.owner_guard(operation="test_persist")


def test_prod_volume_bootstraps_marker_with_existing_data(
    isolated_data_dir, monkeypatch
):
    data = isolated_data_dir
    (data / "soul_map.json").write_text("{}\n")
    monkeypatch.setenv("DATA_DIR_IS_VOLUME", "on")

    ok, detail = og.try_acquire_write_owner_lock()
    assert ok is True
    assert detail == ""
    assert (data / og.VOLUME_MARKER_NAME).is_file()
    assert og.owner_guard_reason() is None


def test_matching_volume_marker_allows_acquire(isolated_data_dir, monkeypatch):
    data = isolated_data_dir
    (data / "soul_map.json").write_text("{}\n")
    monkeypatch.setenv("DATA_DIR_IS_VOLUME", "on")
    fingerprint = og.data_dir_fingerprint()
    (data / og.VOLUME_MARKER_NAME).write_text(
        json.dumps({"version": 1, "fingerprint": fingerprint}) + "\n"
    )

    ok, detail = og.try_acquire_write_owner_lock()
    assert ok is True
    assert detail == ""


def test_unmounted_empty_prod_like_volume_blocked(isolated_data_dir, monkeypatch):
    monkeypatch.setenv("FLY_APP_NAME", "subnet-dashboard")
    monkeypatch.delenv("DATA_DIR_IS_VOLUME", raising=False)

    ok, detail = og.try_acquire_write_owner_lock()
    assert ok is False
    assert detail == "volume_marker_missing"


def test_try_acquire_fails_closed_on_volume_marker_not_ok(isolated_data_dir, monkeypatch):
    """Volume failure must not return ok=True (Ditto high)."""
    monkeypatch.setenv("DATA_DIR_IS_VOLUME", "on")

    ok, detail = og.try_acquire_write_owner_lock()
    assert ok is False
    assert detail == "volume_marker_missing"
    assert og.inspect_owner_guard().writes_allowed is False


def test_wrong_volume_marker_refuses_write(isolated_data_dir, monkeypatch):
    data = isolated_data_dir
    marker = data / og.VOLUME_MARKER_NAME
    marker.write_text(json.dumps({"version": 1, "fingerprint": "wrong:999"}) + "\n")
    monkeypatch.setenv("DATA_DIR_IS_VOLUME", "on")

    ok, detail = og.try_acquire_write_owner_lock()
    assert ok is False
    assert detail == "volume_marker_fingerprint_mismatch"
    assert og.owner_guard_reason() == "volume_marker_fingerprint_mismatch"
    with pytest.raises(og.WriteRefused):
        og.owner_guard()


def test_volume_marker_check_error_releases_lock(isolated_data_dir, monkeypatch):
    real_fp = og.data_dir_fingerprint

    def _flaky_fingerprint():
        if getattr(_flaky_fingerprint, "raised", False):
            return real_fp()
        _flaky_fingerprint.raised = True
        raise OSError(errno.EIO, "simulated stat failure")

    monkeypatch.setattr(og, "data_dir_fingerprint", _flaky_fingerprint)

    ok, detail = og.try_acquire_write_owner_lock()
    assert ok is False
    assert detail.startswith("volume_marker_check_error:")
    assert og.inspect_owner_guard().lock_held is False

    ok2, _ = og.try_acquire_write_owner_lock()
    assert ok2 is True


def test_reads_unaffected_without_owner_guard(isolated_data_dir, monkeypatch):
    data = isolated_data_dir
    soul = data / "soul_map.json"
    soul.write_text('{"x": 1}\n')
    monkeypatch.setenv("DATA_DIR_IS_VOLUME", "on")
    assert og.owner_guard_reason() == "write_owner_lock_not_held"

    from internal.store.soul_map_io import read_soul_map

    assert read_soul_map(str(soul)) == {"x": 1}


def test_lock_released_after_process_exit(isolated_data_dir):
    data = isolated_data_dir
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
    ok, _ = og.try_acquire_write_owner_lock()
    assert ok is True
    assert os.environ.get("DATA_DIR") == str(data)


def test_owner_guard_skip_blocked_in_prod_like(isolated_data_dir, monkeypatch):
    monkeypatch.setenv("DATA_DIR_IS_VOLUME", "on")
    monkeypatch.setenv("OWNER_GUARD_SKIP", "on")

    ok, detail = og.try_acquire_write_owner_lock()
    assert ok is False
    assert detail == "volume_marker_missing"
    assert og.volume_check_prod_like() is True
    assert og.owner_guard_reason() == "volume_marker_missing"


def test_dev_creates_volume_marker_when_not_prod_like(isolated_data_dir, monkeypatch):
    data = isolated_data_dir
    monkeypatch.delenv("DATA_DIR_IS_VOLUME", raising=False)
    monkeypatch.delenv("FLY_APP_NAME", raising=False)

    ok, _ = og.try_acquire_write_owner_lock()
    assert ok is True
    assert og.owner_guard_reason() is None
    marker = json.loads((data / og.VOLUME_MARKER_NAME).read_text())
    assert marker["fingerprint"] == og.data_dir_fingerprint()


def test_flock_non_contention_oserror_reported_as_lock_error(
    isolated_data_dir, monkeypatch
):
    import fcntl as fcntl_mod

    def _boom(_fd, _op):
        raise OSError(errno.EIO, "simulated flock I/O error")

    monkeypatch.setattr(fcntl_mod, "flock", _boom)

    ok, detail = og.try_acquire_write_owner_lock()
    assert ok is False
    assert detail.startswith("write_owner_lock_error:")
    assert "write_owner_lock_contended" not in detail


def test_acquire_write_owner_at_worker_startup_returns_false_on_lock_failure(
    isolated_data_dir, monkeypatch
):
    monkeypatch.setenv("DATA_DIR_IS_VOLUME", "on")
    assert og.acquire_write_owner_at_worker_startup() is False


def test_acquire_write_owner_at_worker_startup_true_after_volume_bootstrap(
    isolated_data_dir, monkeypatch
):
    (isolated_data_dir / "soul_map.json").write_text("{}\n")
    monkeypatch.setenv("DATA_DIR_IS_VOLUME", "on")
    assert og.acquire_write_owner_at_worker_startup() is True


def test_worker_does_not_start_background_writers_when_owner_guard_blocks(
    monkeypatch,
):
    started: list[bool] = []

    def _fake_start(**_kwargs):
        started.append(True)

    monkeypatch.setattr(
        "internal.background_boot.start_background_workers", _fake_start
    )
    monkeypatch.setattr(
        "internal.owner_guard.acquire_write_owner_at_worker_startup",
        lambda: False,
    )
    monkeypatch.setattr("internal.worker.bootstrap_worker_runtime", lambda: None)
    monkeypatch.setattr("internal.process_memory.log_heavy_job_rss", lambda *a, **k: None)
    monkeypatch.setattr(
        "internal.background_boot.schedule_summary_bot_worker_watchdog",
        lambda: None,
    )
    monkeypatch.setattr("internal.background_boot.stop_background_workers", lambda: None)

    from internal import worker as worker_mod

    threading.Timer(0.15, worker_mod._shutdown.set).start()
    worker_mod.main()
    assert started == []
