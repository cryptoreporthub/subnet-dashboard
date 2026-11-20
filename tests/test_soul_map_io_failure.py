"""write_soul_map must not report a mutation the disk did not keep."""

from __future__ import annotations

import json

import pytest

import internal.store.soul_map_io as soul_map_io
from internal.store.soul_map_io import (
    WriteOutcome,
    read_soul_map,
    write_soul_map,
)


def test_replace_oserror_returns_disk_state_and_leaves_cache(
    tmp_path, monkeypatch, caplog
):
    soul_path = tmp_path / "soul_map.json"
    soul_path.write_text(json.dumps({"kept": 1}), encoding="utf-8")
    assert read_soul_map(str(soul_path)) == {"kept": 1}

    def boom(*_args, **_kwargs):
        raise OSError("replace failed")

    monkeypatch.setattr(soul_map_io.os, "replace", boom)
    with caplog.at_level("WARNING"):
        returned = write_soul_map(
            lambda blob: blob.__setitem__("kept", 99),
            path=str(soul_path),
        )

    assert returned.outcome is WriteOutcome.REPLACE_FAILED
    assert returned.blob is None
    assert json.loads(soul_path.read_text(encoding="utf-8")) == {"kept": 1}
    assert read_soul_map(str(soul_path), copy_blob=False) == {"kept": 1}
    assert "soul_map persistence failed" in caplog.text
    assert "OSError" in caplog.text


def test_mutator_timeout_propagates_with_raise_on_lock_timeout(tmp_path):
    """Mutator TimeoutError is not confused with flock lock-wait timeout."""
    soul_path = tmp_path / "soul_map.json"
    soul_path.write_text(json.dumps({"kept": 1}), encoding="utf-8")

    def _slow_mutator(_blob):
        raise TimeoutError("mutator stall")

    with pytest.raises(TimeoutError, match="mutator"):
        write_soul_map(_slow_mutator, path=str(soul_path))
    assert json.loads(soul_path.read_text(encoding="utf-8")) == {"kept": 1}


def test_successful_write_updates_disk_and_cache(tmp_path):
    soul_path = tmp_path / "soul_map.json"
    soul_path.write_text(json.dumps({"kept": 1}), encoding="utf-8")

    returned = write_soul_map(
        lambda blob: blob.__setitem__("kept", 2),
        path=str(soul_path),
    )

    assert returned.outcome is WriteOutcome.APPLIED
    assert returned.blob == {"kept": 2}
    assert json.loads(soul_path.read_text(encoding="utf-8")) == {"kept": 2}
    assert read_soul_map(str(soul_path), copy_blob=False) == {"kept": 2}


def test_mutator_exception_propagates(tmp_path):
    soul_path = tmp_path / "soul_map.json"
    soul_path.write_text(json.dumps({"kept": 1}), encoding="utf-8")

    def explode(blob):
        blob["kept"] = 99
        raise RuntimeError("mutator failed")

    with pytest.raises(RuntimeError, match="mutator failed"):
        write_soul_map(explode, path=str(soul_path))

    assert json.loads(soul_path.read_text(encoding="utf-8")) == {"kept": 1}
    assert read_soul_map(str(soul_path)) == {"kept": 1}


def test_write_soul_map_committed_replace_failed_blob_is_none(
    tmp_path, monkeypatch, caplog
):
    soul_path = tmp_path / "soul_map.json"
    soul_path.write_text(json.dumps({"kept": 1}), encoding="utf-8")

    def boom(*_a, **_kw):
        raise OSError("replace failed")

    monkeypatch.setattr(soul_map_io.os, "replace", boom)
    with caplog.at_level("WARNING"):
        committed, blob = soul_map_io.write_soul_map_committed(
            lambda b: b.__setitem__("kept", 2),
            str(soul_path),
        )

    assert committed is False
    assert blob is None


def test_cache_refresh_failure_after_commit_still_reports_success(
    tmp_path, monkeypatch, caplog
):
    """A cache error after the disk write landed must not report the write as failed."""
    path = tmp_path / "soul_map.json"
    path.write_text(json.dumps({"kept": 1}), encoding="utf-8")
    assert read_soul_map(str(path)) == {"kept": 1}  # populates the cache with the old value

    def boom(*_args, **_kwargs):
        raise RuntimeError("cache broke")

    monkeypatch.setattr(soul_map_io, "_cache_put", boom)
    with caplog.at_level("WARNING"):
        committed, blob = soul_map_io.write_soul_map_committed(
            lambda b: b.__setitem__("kept", 2),
            str(path),
        )

    assert (committed, blob) == (True, {"kept": 2})
    assert json.loads(path.read_text(encoding="utf-8")) == {"kept": 2}
    monkeypatch.undo()
    assert read_soul_map(str(path), copy_blob=False) == {"kept": 2}
    assert "cache refresh failed after commit" in caplog.text
