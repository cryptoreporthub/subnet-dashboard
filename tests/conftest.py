"""
Root conftest — shared fixtures for the full test suite.

The most important fixture here is ``_isolate_message_intel_db``: it redirects
``MESSAGE_INTEL_DB`` to a per-test temporary file so no test can accidentally
write synthetic data into the real ``data/message_intel.db`` that the running
app and proof dashboard depend on.

Tests that supply their own DB fixture (e.g. ``monkeypatch.setenv("MESSAGE_INTEL_DB",
str(tmp_path / "message_intel.db"))``) simply override the env-var again after this
fixture runs — that's fine, because the lru_cache has already been cleared.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolate_message_intel_db(tmp_path, monkeypatch):
    """Redirect message-intel DB to a per-test temp file (prevents live-DB pollution)."""
    db_path = str(tmp_path / "test_message_intel.db")
    monkeypatch.setenv("MESSAGE_INTEL_DB", db_path)
    # Clear the cached DB handle so the redirected path takes effect.
    try:
        from internal.message_intel.store import reset_db_cache

        reset_db_cache()
    except Exception:
        pass
    yield
    # Reset again after the test so the next test starts clean.
    try:
        from internal.message_intel.store import reset_db_cache

        reset_db_cache()
    except Exception:
        pass


@pytest.fixture(autouse=True)
def _isolate_readiness_cache():
    """Prevent readiness cache/refresher state leaking between tests."""
    try:
        from internal.ops.readiness_cache import reset_readiness_cache

        reset_readiness_cache()
    except Exception:
        pass
    yield
    try:
        from internal.ops.readiness_cache import reset_readiness_cache

        reset_readiness_cache()
    except Exception:
        pass


@pytest.fixture(autouse=True)
def _clear_message_intel_load_cache():
    try:
        from internal.message_intel.load_guard import clear_message_intel_load_cache

        clear_message_intel_load_cache()
    except ImportError:
        pass
    yield
    try:
        from internal.message_intel.load_guard import clear_message_intel_load_cache

        clear_message_intel_load_cache()
    except ImportError:
        pass


@pytest.fixture
def usable_soul_map(tmp_path, monkeypatch):
    """A valid soul_map for tests that run the real snapshot producer.

    A missing or corrupt soul_map means "weights unknown", so a build cannot publish without one,
    and a clean checkout has none. Use via ``pytestmark = pytest.mark.usefixtures("usable_soul_map")``.
    """
    from tests.score_snapshot_testutil import install_soul_map

    return install_soul_map(tmp_path, monkeypatch)


_HOLDER_SOURCE = (
    "import sqlite3, sys, time\n"
    "from pathlib import Path\n"
    "from tools.review_orchestrator import db\n"
    "state, tick_id, ready, seconds = (\n"
    "    Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3]), float(sys.argv[4])\n"
    ")\n"
    "# Raw connection on purpose: db.connect() would repair the schema first,\n"
    "# which is exactly what a caller under contention must not be able to do.\n"
    "conn = sqlite3.connect(str(state / db.DB_FILENAME), timeout=30)\n"
    "conn.execute('PRAGMA busy_timeout = 30000')\n"
    "conn.execute('BEGIN IMMEDIATE')\n"
    "conn.execute(\n"
    "    'INSERT INTO ticks (tick_id, started_at, overlap) VALUES (?, ?, 0)',\n"
    "    (tick_id, '2026-01-01T00:00:00+00:00'),\n"
    ")\n"
    "ready.write_text('ready')\n"
    "time.sleep(seconds)\n"
    "conn.execute('ROLLBACK')\n"
    "conn.close()\n"
)


@pytest.fixture
def holding_writer():
    """Run a separate process that holds a write transaction on the store.

    Yields ``hold(state_dir, tick_id, seconds=...)``, a context manager that
    starts the holder, waits until it owns the write lock, and kills it on exit.
    Contention behaviour needs a second *process*: a second connection in the
    same process shares SQLite's lock state and cannot reproduce it.
    """
    import contextlib
    import os
    import subprocess
    import sys
    import time
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[1]

    @contextlib.contextmanager
    def hold(state_dir, tick_id: str, *, seconds: float = 8.0):
        ready = Path(state_dir) / f".holder-ready-{tick_id}"
        env = {**os.environ, "PYTHONPATH": str(repo_root)}
        proc = subprocess.Popen(
            [
                sys.executable,
                "-c",
                _HOLDER_SOURCE,
                str(state_dir),
                tick_id,
                str(ready),
                str(seconds),
            ],
            env=env,
            cwd=str(repo_root),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            deadline = time.monotonic() + 20
            while not ready.exists():
                if proc.poll() is not None:
                    raise AssertionError(
                        "lock holder exited early: " + (proc.stderr.read() or "")
                    )
                if time.monotonic() > deadline:
                    raise AssertionError("lock holder never acquired the write lock")
                time.sleep(0.02)
            yield proc
        finally:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=10)

    return hold
