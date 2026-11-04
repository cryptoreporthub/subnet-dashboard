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


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "pick_day_boundaries: use real pick_day rollover/slot clock (no autouse freeze)",
    )


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


@pytest.fixture(autouse=True)
def _daily_pick_write_token_for_tests():
    """Resolver/pick guarded commits require an issued token (§5)."""
    try:
        from internal.council.daily_pick_write_token import issue_daily_pick_write_token

        issue_daily_pick_write_token()
    except Exception:
        pass


@pytest.fixture(autouse=True)
def _daily_pick_creation_open_for_scheduler(monkeypatch):
    """Keep scheduler unit tests exercising ticks unless they override the gate."""
    try:
        monkeypatch.setattr(
            "internal.council.pick_day.daily_pick_creation_open",
            lambda now=None: True,
        )
        monkeypatch.setattr(
            "internal.council.daily_pick_engine.daily_pick_creation_open",
            lambda now=None: True,
        )
    except Exception:
        pass


@pytest.fixture(autouse=True)
def _stable_default_pick_day_str(monkeypatch, request):
    """Before 14:00 UTC rollover, wall clock would skew pick_day vs calendar tests."""
    if request.node.get_closest_marker("pick_day_boundaries"):
        return
    try:
        fixed = "2026-11-04"

        def _pick_day(now=None):
            return fixed

        for target in (
            "internal.council.pick_day.pick_day_str",
            "internal.council.daily_pick_reader.pick_day_str",
            "internal.council.daily_pick_engine.pick_day_str",
            "internal.learning.loop_health.pick_day_str",
        ):
            try:
                monkeypatch.setattr(target, _pick_day)
            except Exception:
                pass
    except Exception:
        pass


@pytest.fixture
def usable_soul_map(tmp_path, monkeypatch):
    """A valid soul_map for tests that run the real snapshot producer.

    A missing or corrupt soul_map means "weights unknown", so a build cannot publish without one,
    and a clean checkout has none. Use via ``pytestmark = pytest.mark.usefixtures("usable_soul_map")``.
    """
    from tests.score_snapshot_testutil import install_soul_map

    return install_soul_map(tmp_path, monkeypatch)
