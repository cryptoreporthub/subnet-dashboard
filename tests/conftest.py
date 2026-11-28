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

import internal.simivision.caution_cells as caution_cells


@pytest.fixture(autouse=True)
def _isolate_caution_cells_seen(tmp_path, monkeypatch):
    """Warm homepage thread writes caution_cells_seen — keep it off repo data/."""
    caution_path = str(tmp_path / "caution_cells_seen.json")
    monkeypatch.setenv("CAUTION_CELLS_SEEN_PATH", caution_path)
    monkeypatch.setattr(caution_cells, "SEEN_PATH", caution_path)


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
def _isolate_mindmap_state_cache():
    """Prevent mindmap _STATE_CACHE / last-good leaking between tests."""
    from internal.learning.mindmap_aggregator import reset_mindmap_state_cache

    reset_mindmap_state_cache()
    try:
        yield
    finally:
        reset_mindmap_state_cache()


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
