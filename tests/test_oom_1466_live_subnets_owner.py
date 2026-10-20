"""Regression tests for #1466 live_subnets sync ownership and worker supervisor."""

import io
import json
import logging
import os
import subprocess
import sys
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


def test_stop_inline_worker_terminates_setsid_session():
    full = Path("scripts/fly_web_entrypoint.sh").read_text(encoding="utf-8")
    start = full.index("_inline_worker_proc_state()")
    end = full.index("_start_inline_worker()")
    stop_helpers = full[start:end]
    proc = subprocess.Popen(["sleep", "610246"], start_new_session=True)
    try:
        subprocess.run(
            [
                "sh",
                "-c",
                stop_helpers
                + f"""
export INLINE_WORKER_STOP_GRACE_SECONDS=2
_stop_inline_worker "{proc.pid}"
if _inline_worker_live "{proc.pid}"; then
  echo "worker still live"
  exit 1
fi
""",
            ],
            check=True,
            timeout=15,
            cwd=str(Path(__file__).resolve().parents[1]),
        )
        proc.wait(timeout=5)
    finally:
        if proc.poll() is None:
            proc.kill()
