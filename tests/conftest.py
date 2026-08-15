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
