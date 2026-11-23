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

import atexit
import os
import shutil
import tempfile

import pytest

# Module-scoped fixtures and boot threads run outside any per-test fixture. They still must
# not open the repo's data/ledger.db, so the whole session gets a ledger of its own first.
_SESSION_LEDGER_DIR = tempfile.mkdtemp(prefix="ledger-session-")
atexit.register(shutil.rmtree, _SESSION_LEDGER_DIR, True)
os.environ["LEDGER_DB_PATH"] = os.path.join(_SESSION_LEDGER_DIR, "ledger.db")
_REAL_LEDGER = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, "data", "ledger.db")
_REAL_LEDGER_EXISTED = os.path.exists(_REAL_LEDGER)


def pytest_sessionfinish(session, exitstatus):
    """A test run that creates the repo's data/ledger.db has leaked weights into real state."""
    if not _REAL_LEDGER_EXISTED and os.path.exists(_REAL_LEDGER):
        os.unlink(_REAL_LEDGER)
        session.exitstatus = 1
        print("\nFAILED: this test run created data/ledger.db; a test is not isolated from it")


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
def _isolate_learning_effect_receipts(tmp_path, monkeypatch):
    """The resolver writes effect receipts, so no test may share the repo's journal.

    A receipt left by one run makes the next run skip that effect.
    """
    monkeypatch.setenv(
        "LEARNING_EFFECT_RECEIPTS_PATH", str(tmp_path / "learning_effect_receipts.json")
    )


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
def _cancel_background_jobs_armed_by_test():
    """Drop shared-scheduler jobs a test armed and never cancelled.

    A leaked resolver timer fires during a later test and takes the
    process-wide heavy-job slot, so that test sees ``heavy_job_busy``.
    """
    from internal import job_scheduler

    def _jobs():
        sched = job_scheduler._scheduler
        if sched is None:
            return None, set()
        try:
            return sched, {job.id for job in sched.get_jobs()}
        except Exception:
            return None, set()

    _, before = _jobs()
    yield
    sched, after = _jobs()
    for job_id in after - before:
        try:
            sched.remove_job(job_id)
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
def liveness_real_soul_map(tmp_path, monkeypatch):
    """Route internal.liveness soul_map I/O through the real primitive on a temp file."""
    from internal import liveness as _liv_mod
    from internal.store import soul_map_io as smio

    sm_path = tmp_path / "liveness_soul_map.json"

    def _write(mutator, path=None):
        target = str(sm_path) if path is None else path
        return smio.write_soul_map(mutator, target)

    def _read(path=None, **kwargs):
        target = str(sm_path) if path is None else path
        return smio.read_soul_map(target, **kwargs)

    monkeypatch.setattr(_liv_mod, "write_soul_map", _write)
    monkeypatch.setattr(_liv_mod, "read_soul_map", _read)
    return sm_path


@pytest.fixture
def usable_soul_map(tmp_path, monkeypatch):
    """A valid soul_map for tests that run the real snapshot producer.

    A missing or corrupt soul_map means "weights unknown", so a build cannot publish without one,
    and a clean checkout has none. Use via ``pytestmark = pytest.mark.usefixtures("usable_soul_map")``.
    """
    from tests.score_snapshot_testutil import install_soul_map

    return install_soul_map(tmp_path, monkeypatch)


@pytest.fixture(autouse=True)
def _isolate_ledger_db(tmp_path, monkeypatch):
    """Learned weights live in data/ledger.db, so no test may share the repo's file.

    Code that names the real data directory gets a per-test ledger. Code that names a
    temporary soul_map already gets its own ledger.db beside it.
    """
    monkeypatch.setenv("LEDGER_DB_PATH", str(tmp_path / "isolated_ledger.db"))

