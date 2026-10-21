"""Regression tests for #1466 live_subnets sync ownership and worker supervisor."""

import io
import json
import logging
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

import pytest

FLY_PROD_ENV = {
    "RUN_MODE": "web",
    "BACKGROUND_ON_WEB": "off",
    "INLINE_WORKER": "1",
    "ENABLE_INLINE_WORKER": "1",
    "WORKER_SPLIT_V2": "off",
    "WORKER_HEAVY": "essential",
}


def _write_stale_cache(tmp_path) -> None:
    cache = {
        "synced_at": "2000-01-01T00:00:00+00:00",
        "subnets": [{"netuid": 1, "live": True}],
    }
    path = tmp_path / "live_subnets.json"
    path.write_text(json.dumps(cache), encoding="utf-8")


@pytest.fixture(autouse=True)
def _reset_live_subnets_sync_state(monkeypatch):
    from internal import live_subnets

    monkeypatch.setattr(live_subnets, "_sync_loop_running", False, raising=False)


def test_fly_toml_prod_worker_owns_sync_web_read_only(monkeypatch):
    from internal.run_mode import live_subnets_sync_owner_enabled

    for key, value in FLY_PROD_ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("RUN_MODE", "worker")
    assert live_subnets_sync_owner_enabled() is True

    for key, value in FLY_PROD_ENV.items():
        monkeypatch.setenv(key, value)
    assert live_subnets_sync_owner_enabled() is False


def test_get_live_subnets_is_pure_read_on_web(monkeypatch, tmp_path):
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    for key, value in FLY_PROD_ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("LIVE_SUBNETS_AUTO_SYNC", "true")
    _write_stale_cache(tmp_path)

    from internal import live_subnets

    monkeypatch.setattr(live_subnets, "_in_ci_or_test", False)
    with (
        patch.object(live_subnets, "_sync_loop", lambda: None),
        patch.object(live_subnets, "_sync_once") as sync,
        patch.object(live_subnets, "start_live_subnets_sync") as start,
    ):
        rows = live_subnets.get_live_subnets()
    assert rows
    sync.assert_not_called()
    start.assert_not_called()
    assert live_subnets._sync_loop_running is False


def test_get_live_subnets_does_not_start_sync_on_essential_worker(monkeypatch, tmp_path):
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUN_MODE", "worker")
    monkeypatch.setenv("WORKER_HEAVY", "essential")
    monkeypatch.setenv("LIVE_SUBNETS_AUTO_SYNC", "true")
    _write_stale_cache(tmp_path)

    from internal import live_subnets

    monkeypatch.setattr(live_subnets, "_in_ci_or_test", False)
    with (
        patch.object(live_subnets, "_sync_loop", lambda: None),
        patch.object(live_subnets, "_sync_once") as sync,
        patch.object(live_subnets, "start_live_subnets_sync") as start,
    ):
        live_subnets.get_live_subnets()
    sync.assert_not_called()
    start.assert_not_called()


def test_start_live_subnets_sync_owner_only(monkeypatch, tmp_path):
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUN_MODE", "worker")
    monkeypatch.setenv("WORKER_HEAVY", "essential")
    monkeypatch.setenv("LIVE_SUBNETS_AUTO_SYNC", "true")

    from internal import live_subnets

    monkeypatch.setattr(live_subnets, "_in_ci_or_test", False)
    monkeypatch.setattr(live_subnets, "AUTO_SYNC", True)
    with patch.object(live_subnets, "_ensure_sync_loop") as ensure:
        live_subnets.start_live_subnets_sync()
    ensure.assert_called_once()

    monkeypatch.setenv("RUN_MODE", "web")
    for key, value in FLY_PROD_ENV.items():
        monkeypatch.setenv(key, value)
    with patch.object(live_subnets, "_ensure_sync_loop") as ensure_web:
        live_subnets.start_live_subnets_sync()
    ensure_web.assert_not_called()


def test_fetch_child_refused_on_web(monkeypatch):
    monkeypatch.setenv("RUN_MODE", "web")
    for key, value in FLY_PROD_ENV.items():
        monkeypatch.setenv(key, value)
    from internal import live_subnets

    monkeypatch.setattr(live_subnets, "_in_ci_or_test", False)
    monkeypatch.setattr(live_subnets, "AUTO_SYNC", True)
    assert live_subnets._fetch_chain_data() is None


def test_app_logging_pid_in_formatted_record():
    from internal.app_logging import _HANDLER_NAME, configure_app_logging

    configure_app_logging()
    root = logging.getLogger()
    handler = next(h for h in root.handlers if h.get_name() == _HANDLER_NAME)
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="probe",
        args=(),
        exc_info=None,
    )
    out = io.StringIO()
    handler.setStream(out)
    handler.emit(record)
    line = out.getvalue()
    assert f"pid={os.getpid()}" in line


def test_set_linux_process_comm_sets_proc_comm():
    code = """
from internal.process_memory import set_linux_process_comm
set_linux_process_comm("live-subnets-fetch")
with open("/proc/self/comm", encoding="utf-8") as f:
    print(f.read().strip())
"""
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(Path(__file__).resolve().parents[1]),
        capture_output=True,
        text=True,
        check=True,
    )
    comm = proc.stdout.strip()
    assert comm.startswith("live-subnets")


def _repo_entrypoint_text() -> str:
    return Path("scripts/fly_web_entrypoint.sh").read_text(encoding="utf-8")


def _entrypoint_library_src(entrypoint_src: str) -> str:
    """Functions only — do not source trailing boot/supervisor invocations."""
    lines = entrypoint_src.splitlines(keepends=True)
    for i, line in enumerate(lines):
        if line.startswith('case "${ENABLE_INLINE_WORKER'):
            return "".join(lines[:i])
    raise ValueError("entrypoint boot marker missing")


def _inline_worker_group_live(pgid: str, entrypoint_src: str) -> bool:
    if not pgid:
        return False
    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".sh",
        encoding="utf-8",
        delete=False,
    ) as script:
        script.write(_entrypoint_library_src(entrypoint_src))
        script_path = script.name
    try:
        proc = subprocess.run(
            [
                "dash",
                "-c",
                f'. "{script_path}"; _inline_worker_group_live "{pgid}"',
            ],
            capture_output=True,
            check=False,
        )
        return proc.returncode == 0
    finally:
        os.unlink(script_path)


def _git_show_entrypoint(rev: str) -> str:
    repo = Path(__file__).resolve().parents[1]
    proc = subprocess.run(
        ["git", "show", f"{rev}:scripts/fly_web_entrypoint.sh"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
    return proc.stdout


def _pids_matching(pattern: str) -> set[str]:
    out = subprocess.run(
        ["pgrep", "-f", pattern],
        capture_output=True,
        text=True,
        check=False,
    ).stdout
    return {p for p in out.split() if p}


def _stub_ps_absent(tmp_path: Path) -> str:
    no_ps_bin = tmp_path / "bin"
    no_ps_bin.mkdir(exist_ok=True)
    (no_ps_bin / "ps").write_text("#!/bin/sh\nexit 127\n", encoding="utf-8")
    (no_ps_bin / "ps").chmod(0o755)
    return str(no_ps_bin)


def _patch_entrypoint_for_harness(entrypoint_src: str, web_sleep_id: str) -> str:
    return entrypoint_src.replace(
        "exec python scripts/run_web_with_guard.py",
        f"exec sleep {web_sleep_id}\n",
    )


def _run_supervisor_stale_heartbeat_harness(
    tmp_path: Path,
    entrypoint_src: str,
    *,
    parent_sleep_id: str,
    child_sleep_id: str,
    web_sleep_id: str,
    group_live_check: str | None = None,
) -> None:
    """TERM-ignoring worker with a child; ps absent on PATH. Raises on failure."""
    live_src = group_live_check if group_live_check is not None else entrypoint_src
    repo = Path(__file__).resolve().parents[1]
    hb_path = tmp_path / "hb.json"
    pidfile = tmp_path / "inline_worker.pid"
    no_ps_prefix = _stub_ps_absent(tmp_path)
    src = _patch_entrypoint_for_harness(entrypoint_src, web_sleep_id)
    launch = (
        f"sh -c 'trap \"\" TERM; (exec sleep {child_sleep_id}) & exec sleep {parent_sleep_id}'"
    )
    env = os.environ.copy()
    env.update(
        {
            "INLINE_WORKER_PIDFILE": str(pidfile),
            "INLINE_WORKER_SUPERVISOR_SLEEP_SECONDS": "1",
            "INLINE_WORKER_STOP_GRACE_SECONDS": "2",
            "INLINE_WORKER_LAUNCH": launch,
            "WORKER_HEARTBEAT_PATH": str(hb_path),
            "ENABLE_INLINE_WORKER": "1",
            "WORKER_SPLIT_V2": "0",
            "PYTHONPATH": str(repo),
            "PATH": f"{no_ps_prefix}:{env.get('PATH', '')}",
        }
    )
    log_path = tmp_path / "entrypoint_supervisor.log"
    log_handle = log_path.open("w", encoding="utf-8")
    proc = subprocess.Popen(
        ["dash", "-c", src],
        env=env,
        cwd=str(repo),
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        text=True,
        start_new_session=True,
    )
    for pattern in (parent_sleep_id, child_sleep_id):
        subprocess.run(["pkill", "-9", "-f", pattern], check=False)
    time.sleep(0.2)
    first_pgid = ""
    first_pids: set[str] = set()
    second_start_seen = False
    try:
        time.sleep(0.5)
        assert pidfile.is_file(), "supervisor did not start inline worker"
        first_pgid = pidfile.read_text(encoding="utf-8").strip()
        first_pids = _pids_matching(parent_sleep_id) | _pids_matching(child_sleep_id)
        assert first_pids, "worker parent/child sleep processes not running after boot"
        assert len(first_pids) >= 2, f"expected parent+child, saw {first_pids!r}"
        hb_path.write_text(
            json.dumps({"ts": "2000-01-01T00:00:00Z", "pid": 1}),
            encoding="utf-8",
        )
        deadline = time.time() + 14
        while time.time() < deadline:
            out = log_path.read_text(encoding="utf-8")
            starts = out.count("starting inline background worker")
            if starts >= 2 and not second_start_seen:
                assert not _inline_worker_group_live(first_pgid, live_src), (
                    f"old pgid {first_pgid} still live at 2nd worker start"
                )
                overlap = first_pids & (
                    _pids_matching(parent_sleep_id) | _pids_matching(child_sleep_id)
                )
                assert not overlap, (
                    f"old worker descendants still alive at 2nd start: {overlap}"
                )
                second_start_seen = True
            if second_start_seen and "sending SIGKILL" in out:
                break
            time.sleep(0.25)
        time.sleep(1)
        listed = subprocess.run(
            ["pgrep", "-af", parent_sleep_id],
            capture_output=True,
            text=True,
            check=False,
        ).stdout.strip()
        final_pids = _pids_matching(parent_sleep_id) | _pids_matching(child_sleep_id)
        count = len(final_pids)
        assert count <= 2, f"expected at most one worker pair, saw {count} ({listed!r})"
        assert first_pids.isdisjoint(final_pids), (
            f"stale worker pids still alive: {first_pids & final_pids}"
        )
        out = log_path.read_text(encoding="utf-8")
        assert out.count("starting inline background worker") >= 2, out
        assert second_start_seen, "never observed 2nd start with old pgid dead"
        assert "heartbeat stale" in out, out
        assert "sending SIGKILL" in out, out
        idx_first = out.find("starting inline background worker")
        idx_second = out.find("starting inline background worker", idx_first + 1)
        assert idx_second > idx_first
        between = out[idx_first:idx_second]
        assert "heartbeat stale" in between or "heartbeat stale" in out[:idx_second]
    finally:
        log_handle.close()
        if proc.poll() is None:
            try:
                os.killpg(os.getpgid(proc.pid), 9)
            except ProcessLookupError:
                proc.kill()
            proc.wait(timeout=5)
        for pattern in (parent_sleep_id, child_sleep_id, web_sleep_id):
            subprocess.run(["pkill", "-9", "-f", pattern], check=False)


def _run_churn_group_live_checks(
    entrypoint_src: str,
    *,
    target: str,
    iterations: int,
    assert_stable_with: str | None = None,
) -> int:
    worker = subprocess.Popen(["setsid", "sleep", target])
    churn = subprocess.Popen(
        ["dash", "-c", "while true; do (sleep 0.01 &); done"],
        start_new_session=True,
    )
    false_dead = 0
    try:
        time.sleep(0.3)
        pgid = str(worker.pid)
        os.kill(worker.pid, 0)
        stable_src = assert_stable_with if assert_stable_with is not None else entrypoint_src
        assert _inline_worker_group_live(pgid, stable_src), (
            "stable worker group not visible before churn"
        )
        for _ in range(iterations):
            if not _inline_worker_group_live(pgid, entrypoint_src):
                false_dead += 1
    finally:
        for proc in (worker, churn):
            if proc.poll() is None:
                try:
                    os.killpg(os.getpgid(proc.pid), 9)
                except ProcessLookupError:
                    proc.kill()
                proc.wait(timeout=5)
        subprocess.run(["pkill", "-9", "-f", target], check=False)
    return false_dead


def test_proc_pgid_scan_mawk_no_false_dead_under_churn():
    false_dead = _run_churn_group_live_checks(
        _repo_entrypoint_text(),
        target="61999009888",
        iterations=80,
    )
    assert false_dead == 0, (
        f"_inline_worker_group_live reported dead {false_dead}/80 under churn"
    )


def test_proc_pgid_scan_mawk_churn_false_dead_without_cat_snapshot():
    pre_cat = _git_show_entrypoint("fb1fdb8e")
    false_dead = _run_churn_group_live_checks(
        pre_cat,
        target="61999009890",
        iterations=120,
        assert_stable_with=_repo_entrypoint_text(),
    )
    assert false_dead >= 1, (
        "fb1fdb8e awk-on-glob scan should false-negative under /proc churn"
    )


def test_entrypoint_supervisor_replaces_hung_worker_without_ps(tmp_path):
    parent_sleep_id = "61999001248"
    child_sleep_id = "61999001250"
    web_sleep_id = "61999001249"
    entrypoint_src = _repo_entrypoint_text()
    _run_supervisor_stale_heartbeat_harness(
        tmp_path,
        entrypoint_src,
        parent_sleep_id=parent_sleep_id,
        child_sleep_id=child_sleep_id,
        web_sleep_id=web_sleep_id,
    )


def test_supervisor_stale_heartbeat_harness_fails_on_merge_base_entrypoint(tmp_path):
    base_entrypoint = _git_show_entrypoint("057eabf7")
    with pytest.raises(AssertionError):
        _run_supervisor_stale_heartbeat_harness(
            tmp_path,
            base_entrypoint,
            parent_sleep_id="61999001251",
            child_sleep_id="61999001252",
            web_sleep_id="61999001253",
        )


def test_supervisor_stale_heartbeat_harness_fails_with_pre_cat_entrypoint(tmp_path):
    pre_cat = _git_show_entrypoint("fb1fdb8e")
    with pytest.raises(AssertionError):
        _run_supervisor_stale_heartbeat_harness(
            tmp_path,
            pre_cat,
            parent_sleep_id="61999001254",
            child_sleep_id="61999001255",
            web_sleep_id="61999001256",
        )
