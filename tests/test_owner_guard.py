"""Single-writer step 1: owner lock + volume marker (fail-closed writes)."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import textwrap
import uuid
from unittest import mock

import pytest

import internal.data_volume as dv
import internal.file_utils as file_utils
import internal.owner_guard as og

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _mountinfo_line(mount_point: str, source: str = "/dev/vdc", fstype: str = "ext4") -> str:
    return f"999 998 0:42 / {mount_point} rw,relatime - {fstype} {source} rw"


def _fake_mountinfo_for(data_dir: os.PathLike[str]) -> list[str]:
    root = os.path.realpath(str(data_dir))
    return [_mountinfo_line(root)]


def _write_v2_marker(
    data_dir: os.PathLike[str],
    *,
    volume_id: str | None = None,
    app_name: str = "subnet-dashboard",
    pinned_volume_id: str = "vol_test123",
) -> None:
    payload = {
        "version": 2,
        "volume_id": volume_id or uuid.uuid4().hex,
        "app_name": app_name,
        "pinned_volume_id": pinned_volume_id,
        "created_at": "2026-01-01T00:00:00+00:00",
    }
    (data_dir / og.VOLUME_MARKER_NAME).write_text(json.dumps(payload) + "\n")


@pytest.fixture
def owner_env(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    saved_handlers = (
        signal.getsignal(signal.SIGTERM),
        signal.getsignal(signal.SIGINT),
    )
    for key in (
        "FLY_APP_NAME",
        "FLY_MACHINE_ID",
        "DATA_DIR_IS_VOLUME",
        "OWNER_GUARD_SKIP",
        "DATA_VOLUME_ID",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("DATA_DIR", str(data))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(file_utils, "DATA_DIR", str(data))
    og.reset_owner_guard_for_tests()
    yield data
    og.reset_owner_guard_for_tests()
    signal.signal(signal.SIGTERM, saved_handlers[0])
    signal.signal(signal.SIGINT, saved_handlers[1])
    from internal import worker as worker_mod

    worker_mod._shutdown.clear()


@pytest.fixture
def prod_mount(owner_env, monkeypatch):
    data = owner_env
    monkeypatch.setenv("FLY_APP_NAME", "subnet-dashboard")
    monkeypatch.setenv("DATA_VOLUME_ID", "vol_test123")
    monkeypatch.setattr(
        dv, "_read_mountinfo", lambda: _fake_mountinfo_for(data)
    )
    return data


def test_second_process_cannot_acquire_lock_while_first_holds(owner_env, monkeypatch):
    data = owner_env
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
        env=_subprocess_env(),
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


def test_matching_marker_on_plain_dir_blocked_in_prod_like(owner_env, monkeypatch):
    data = owner_env
    monkeypatch.setenv("FLY_APP_NAME", "subnet-dashboard")
    monkeypatch.setenv("DATA_VOLUME_ID", "vol_test123")
    _write_v2_marker(data)
    monkeypatch.setattr(dv, "_read_mountinfo", lambda: [])

    ok, detail = og.try_acquire_write_owner_lock()
    assert ok is False
    assert detail.startswith("mount_unproven:")


def test_data_dir_is_volume_env_does_not_prove_mount(owner_env, monkeypatch):
    monkeypatch.setenv("DATA_DIR_IS_VOLUME", "on")
    monkeypatch.setenv("FLY_APP_NAME", "subnet-dashboard")
    monkeypatch.setenv("DATA_VOLUME_ID", "vol_test123")
    monkeypatch.setattr(dv, "_read_mountinfo", lambda: [])

    ok, detail = og.try_acquire_write_owner_lock()
    assert ok is False
    assert detail.startswith("mount_unproven:")


def test_parent_mount_does_not_prove_volume(owner_env, monkeypatch):
    data = owner_env
    monkeypatch.setenv("FLY_APP_NAME", "subnet-dashboard")
    monkeypatch.setenv("DATA_VOLUME_ID", "vol_test123")
    root = os.path.realpath(str(data))
    parent = os.path.dirname(root)
    monkeypatch.setattr(
        dv, "_read_mountinfo", lambda: [_mountinfo_line(parent)]
    )
    ok, detail = og.try_acquire_write_owner_lock()
    assert ok is False
    assert detail.startswith("mount_unproven:")


def test_bootstrap_requires_volume_data(prod_mount):
    data = prod_mount
    ok, detail = og.try_acquire_write_owner_lock()
    assert ok is False
    assert detail == "marker_absent_no_data"
    (data / ".worker_heartbeat").write_text("x\n")
    og.reset_owner_guard_for_tests()
    ok2, detail2 = og.try_acquire_write_owner_lock()
    assert ok2 is False
    assert detail2 == "marker_absent_no_data"


def test_prod_volume_bootstraps_marker_with_existing_data(prod_mount):
    data = prod_mount
    (data / "soul_map.json").write_text("{}\n")
    ok, detail = og.try_acquire_write_owner_lock()
    assert ok is True
    assert detail == ""
    assert (data / og.VOLUME_MARKER_NAME).is_file()
    marker = json.loads((data / og.VOLUME_MARKER_NAME).read_text())
    assert marker["version"] == 2
    assert marker["pinned_volume_id"] == "vol_test123"
    assert og.owner_guard_reason() is None


@pytest.mark.parametrize(
    "body",
    [
        "",
        "{",
        "[]",
        json.dumps({"version": 1, "volume_id": "x" * 32}),
        json.dumps({"version": 2, "volume_id": "short", "app_name": ""}),
    ],
)
def test_corrupt_marker_never_overwritten(prod_mount, body):
    data = prod_mount
    (data / "soul_map.json").write_text("{}\n")
    path = data / og.VOLUME_MARKER_NAME
    path.write_text(body)
    before = path.read_bytes()
    ok, _ = og.try_acquire_write_owner_lock()
    assert ok is False
    assert path.read_bytes() == before


def test_unreadable_marker_blocks(prod_mount):
    data = prod_mount
    (data / "soul_map.json").write_text("{}\n")
    path = data / og.VOLUME_MARKER_NAME
    path.mkdir()
    ok, detail = og.try_acquire_write_owner_lock()
    assert ok is False
    assert "marker_" in detail
    assert path.is_dir()


def test_app_name_mismatch_blocks(prod_mount):
    data = prod_mount
    (data / "soul_map.json").write_text("{}\n")
    _write_v2_marker(data, app_name="other-app")
    ok, detail = og.try_acquire_write_owner_lock()
    assert ok is False
    assert "marker_mismatch" in detail


def test_pin_mismatch_blocks(prod_mount):
    data = prod_mount
    (data / "soul_map.json").write_text("{}\n")
    _write_v2_marker(data, pinned_volume_id="vol_wrong")
    ok, detail = og.try_acquire_write_owner_lock()
    assert ok is False
    assert "marker_mismatch" in detail


def test_pin_required_in_prod_bootstrap(prod_mount, monkeypatch):
    data = prod_mount
    (data / "soul_map.json").write_text("{}\n")
    monkeypatch.delenv("DATA_VOLUME_ID", raising=False)
    ok, detail = og.try_acquire_write_owner_lock()
    assert ok is False
    assert detail == "volume_pin_missing"


def test_inspect_never_writes_marker(owner_env, monkeypatch):
    monkeypatch.setenv("OWNER_GUARD_SKIP", "on")
    og.inspect_owner_guard()
    assert not (owner_env / og.VOLUME_MARKER_NAME).exists()


def test_bootstrap_atomic_create_if_absent(prod_mount, monkeypatch):
    data = prod_mount
    (data / "soul_map.json").write_text("{}\n")
    real_link = os.link
    linked = {"done": False}

    def _link_once(src, dst):
        if not linked["done"]:
            linked["done"] = True
            raise FileExistsError()
        return real_link(src, dst)

    monkeypatch.setattr(os, "link", _link_once)
    _write_v2_marker(data)
    og.reset_owner_guard_for_tests()
    ok, _ = og.try_acquire_write_owner_lock()
    assert ok is True


def test_matching_volume_marker_allows_acquire(prod_mount):
    data = prod_mount
    (data / "soul_map.json").write_text("{}\n")
    _write_v2_marker(data)
    ok, detail = og.try_acquire_write_owner_lock()
    assert ok is True
    assert detail == ""


def test_try_acquire_fails_closed_on_volume_marker_not_ok(prod_mount):
    ok, detail = og.try_acquire_write_owner_lock()
    assert ok is False
    assert detail == "marker_absent_no_data"
    assert og.inspect_owner_guard().writes_allowed is False


def test_volume_marker_check_error_releases_lock(prod_mount, monkeypatch):
    (prod_mount / "soul_map.json").write_text("{}\n")
    calls = {"n": 0}
    real = og._classify_marker

    def flaky(root):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError(5, "simulated")
        return real(root)

    monkeypatch.setattr(og, "_classify_marker", flaky)
    ok, detail = og.try_acquire_write_owner_lock()
    assert ok is False
    assert detail.startswith("volume_check_error:")
    assert og.inspect_owner_guard().lock_held is False
    og.reset_owner_guard_for_tests()
    ok2, _ = og.try_acquire_write_owner_lock()
    assert ok2 is True


def test_reads_unaffected_without_owner_guard(owner_env):
    soul = owner_env / "soul_map.json"
    soul.write_text('{"x": 1}\n')
    assert og.owner_guard_reason() == "write_owner_lock_not_held"
    from internal.store.soul_map_io import read_soul_map

    assert read_soul_map(str(soul)) == {"x": 1}


def test_lock_released_after_process_exit(owner_env, monkeypatch):
    data = owner_env
    monkeypatch.setenv("OWNER_GUARD_SKIP", "on")
    script = textwrap.dedent(
        f"""
        import os
        os.environ["DATA_DIR"] = {str(data)!r}
        os.environ["OWNER_GUARD_SKIP"] = "on"
        from internal.owner_guard import try_acquire_write_owner_lock
        ok, _ = try_acquire_write_owner_lock()
        assert ok
        """
    )
    subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        cwd=os.getcwd(),
        env=_subprocess_env(),
    )
    og.reset_owner_guard_for_tests()
    ok, _ = og.try_acquire_write_owner_lock()
    assert ok is True


def test_owner_guard_skip_blocked_in_prod_like(prod_mount, monkeypatch):
    monkeypatch.setenv("OWNER_GUARD_SKIP", "on")
    ok, detail = og.try_acquire_write_owner_lock()
    assert ok is False
    assert detail in ("volume_pin_missing", "marker_absent_no_data")


def test_dev_creates_volume_marker_when_not_prod_like(owner_env, monkeypatch):
    data = owner_env
    ok, _ = og.try_acquire_write_owner_lock()
    assert ok is True
    marker = json.loads((data / og.VOLUME_MARKER_NAME).read_text())
    assert marker["version"] == 2


def test_flock_non_contention_oserror_reported_as_lock_error(owner_env, monkeypatch):
    import fcntl as fcntl_mod

    real_flock = fcntl_mod.flock

    def _boom(fd, op):
        if op & fcntl_mod.LOCK_NB:
            raise OSError(5, "simulated flock I/O error")
        return real_flock(fd, op)

    monkeypatch.setattr(fcntl_mod, "flock", _boom)
    ok, detail = og.try_acquire_write_owner_lock()
    assert ok is False
    assert detail.startswith("write_owner_lock_error:")


def test_acquire_write_owner_at_worker_startup_returns_false_on_lock_failure(prod_mount):
    ok, _ = og.acquire_write_owner_at_worker_startup()
    assert ok is False


def test_acquire_write_owner_at_worker_startup_true_after_volume_bootstrap(prod_mount):
    (prod_mount / "soul_map.json").write_text("{}\n")
    ok, _ = og.acquire_write_owner_at_worker_startup()
    assert ok is True


def test_owner_guard_does_not_create_data_dir_in_prod_like(tmp_path, monkeypatch):
    rel = tmp_path / "nested" / "data"
    monkeypatch.setenv("DATA_DIR", "nested/data")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("FLY_APP_NAME", "subnet-dashboard")
    monkeypatch.setenv("DATA_VOLUME_ID", "vol_test123")
    og.reset_owner_guard_for_tests()
    ok, detail = og.try_acquire_write_owner_lock()
    assert ok is False
    assert detail == "data_dir_missing"
    assert not rel.exists()


def test_lock_file_replaced_blocks_writes(prod_mount):
    data = prod_mount
    (data / "soul_map.json").write_text("{}\n")
    _write_v2_marker(data)
    ok, _ = og.try_acquire_write_owner_lock()
    assert ok is True
    lock_path = data / og.WRITE_OWNER_LOCK_NAME
    lock_path.unlink()
    lock_path.write_text("replaced\n")
    assert og.owner_guard_reason() is not None
    assert og.owner_guard_reason().startswith("owner_lost:")


def test_marker_changed_after_acquire_blocks_writes(prod_mount):
    data = prod_mount
    (data / "soul_map.json").write_text("{}\n")
    _write_v2_marker(data)
    ok, _ = og.try_acquire_write_owner_lock()
    assert ok is True
    path = data / og.VOLUME_MARKER_NAME
    content = path.read_text()
    path.unlink()
    path.write_text(content + " ")
    reason = og.owner_guard_reason()
    assert reason is not None
    assert reason.startswith("owner_lost:")


def test_symlinked_marker_refused(prod_mount):
    data = prod_mount
    (data / "soul_map.json").write_text("{}\n")
    target = data / "real.json"
    target.write_text('{"version": 2}\n')
    link = data / og.VOLUME_MARKER_NAME
    if link.exists():
        link.unlink()
    os.symlink(target, link)
    ok, detail = og.try_acquire_write_owner_lock()
    assert ok is False


def test_symlinked_lock_refused(prod_mount):
    data = prod_mount
    (data / "soul_map.json").write_text("{}\n")
    _write_v2_marker(data)
    lock = data / og.WRITE_OWNER_LOCK_NAME
    if lock.exists():
        lock.unlink()
    os.symlink(data / og.VOLUME_MARKER_NAME, lock)
    ok, detail = og.try_acquire_write_owner_lock()
    assert ok is False
    assert detail == "lock_not_regular"


def _subprocess_env(**extra: str) -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = _REPO_ROOT
    env.update(extra)
    return env


def _fork_subprocess(script: str, timeout: float = 15) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", script],
        cwd=os.getcwd(),
        env=_subprocess_env(),
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def test_forked_child_cannot_pass_guard_subprocess(owner_env):
    data = owner_env
    script = textwrap.dedent(
        f"""
        import os, sys
        os.environ["DATA_DIR"] = {str(data)!r}
        os.environ["OWNER_GUARD_SKIP"] = "on"
        from internal.owner_guard import try_acquire_write_owner_lock, owner_guard, WriteRefused
        ok, _ = try_acquire_write_owner_lock()
        assert ok
        pid = os.fork()
        if pid == 0:
            try:
                owner_guard()
                print("CHILD_OK", flush=True)
            except WriteRefused:
                print("CHILD_REFUSED", flush=True)
            os._exit(0)
        else:
            import os as _os
            _os.waitpid(pid, 0)
            print("PARENT_DONE", flush=True)
        """
    )
    result = _fork_subprocess(script)
    assert "CHILD_REFUSED" in result.stdout


def test_fork_interleaving_subprocess(owner_env):
    data = owner_env
    script = textwrap.dedent(
        f"""
        import os
        os.environ["DATA_DIR"] = {str(data)!r}
        import internal.owner_guard as og

        def hook():
            pid = os.fork()
            if pid == 0:
                ok, detail = og.try_acquire_write_owner_lock()
                print(f"CHILD={{ok}}|{{detail}}", flush=True)
                os._exit(0)
            os.waitpid(pid, 0)

        og._after_flock_hook = hook
        ok, _ = og.try_acquire_write_owner_lock()
        og._after_flock_hook = None
        print(f"PARENT={{ok}}", flush=True)
        """
    )
    result = _fork_subprocess(script, timeout=15)
    assert "PARENT=True" in result.stdout
    assert "CHILD=False|write_owner_lock_contended" in result.stdout


def test_worker_blocked_exits_3_and_never_logs_running(prod_mount, monkeypatch, caplog):
    import logging

    caplog.set_level(logging.ERROR)
    term_before = (
        signal.getsignal(signal.SIGTERM),
        signal.getsignal(signal.SIGINT),
    )
    monkeypatch.setattr("internal.worker.bootstrap_worker_runtime", lambda: None)
    monkeypatch.setattr(
        "internal.background_boot.start_background_workers", lambda **k: None
    )
    from internal import worker as worker_mod

    with pytest.raises(SystemExit) as exc:
        worker_mod.main()
    assert exc.value.code == 3
    assert signal.getsignal(signal.SIGTERM) == term_before[0]
    assert not worker_mod._shutdown.is_set()
    assert "background worker running" not in caplog.text


def test_worker_blocked_subprocess_e2e(prod_mount):
    data = prod_mount
    env = _subprocess_env(
        DATA_DIR=str(data),
        FLY_APP_NAME="subnet-dashboard",
    )
    env.pop("DATA_VOLUME_ID", None)
    proc = subprocess.run(
        [sys.executable, "-m", "internal.worker"],
        cwd=os.getcwd(),
        env=env,
        capture_output=True,
        timeout=30,
    )
    assert proc.returncode == 3


def test_server_lifespan_blocked_worker_exits(prod_mount, monkeypatch):
    monkeypatch.setenv("RUN_MODE", "worker")
    monkeypatch.setattr(
        "internal.run_mode.background_boot_allowed", lambda: True
    )
    monkeypatch.setattr("internal.run_mode.is_worker_mode", lambda: True)
    monkeypatch.setattr("internal.run_mode.stage2_hop_mode", lambda: False)
    started = []

    def _start(**_kwargs):
        started.append(True)

    monkeypatch.setattr(
        "internal.background_boot.start_background_workers", _start
    )
    monkeypatch.setattr(
        "internal.owner_guard.acquire_or_refuse", lambda _ctx: False
    )
    from server import _lifespan

    app = mock.MagicMock()

    async def _run():
        async with _lifespan(app):
            pass

    with pytest.raises(SystemExit) as exc:
        import asyncio

        asyncio.run(_run())
    assert exc.value.code == 3
    assert started == []


def test_server_web_background_path_gated(prod_mount, monkeypatch):
    monkeypatch.setenv("RUN_MODE", "web")
    monkeypatch.setattr("internal.run_mode.is_worker_mode", lambda: False)
    monkeypatch.setattr("internal.run_mode.background_on_web", lambda: True)
    monkeypatch.setattr(
        "internal.run_mode.background_boot_allowed", lambda: True
    )
    started = []

    def _start(**_kwargs):
        started.append(True)

    monkeypatch.setattr(
        "internal.background_boot.start_background_workers", _start
    )
    monkeypatch.setattr(
        "internal.owner_guard.acquire_or_refuse", lambda _ctx: False
    )
    from server import _lifespan

    app = mock.MagicMock()

    async def _run():
        async with _lifespan(app):
            pass

    import asyncio

    asyncio.run(_run())
    assert started == []


def test_failed_bootstrap_leaves_no_tmp(prod_mount, monkeypatch):
    data = prod_mount
    (data / "soul_map.json").write_text("{}\n")

    def _fail_link(*_a, **_k):
        raise OSError(28, "no space")

    monkeypatch.setattr(os, "link", _fail_link)
    ok, _ = og.try_acquire_write_owner_lock()
    assert ok is False
    tmps = list(data.glob(f"{og.VOLUME_MARKER_NAME}.*.tmp"))
    assert tmps == []
