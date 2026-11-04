"""write_soul_map must not report a mutation the disk did not keep."""

from __future__ import annotations

import json

import pytest

import internal.store.soul_map_io as soul_map_io
from internal.store.soul_map_io import read_soul_map, write_soul_map


def test_replace_oserror_returns_disk_state_and_leaves_cache(tmp_path, monkeypatch, caplog):
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

    assert returned == {"kept": 1}
    assert json.loads(soul_path.read_text(encoding="utf-8")) == {"kept": 1}
    assert read_soul_map(str(soul_path), copy_blob=False) == {"kept": 1}
    assert "soul_map persistence failed" in caplog.text
    assert "OSError" in caplog.text


def test_successful_write_updates_disk_and_cache(tmp_path):
    soul_path = tmp_path / "soul_map.json"
    soul_path.write_text(json.dumps({"kept": 1}), encoding="utf-8")

    returned = write_soul_map(
        lambda blob: blob.__setitem__("kept", 2),
        path=str(soul_path),
    )

    assert returned == {"kept": 2}
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


def test_write_leaves_unreadable_existing_file_untouched(tmp_path):
    from internal.store import soul_map_io

    path = tmp_path / "soul_map.json"
    corrupt = '{"soul_map_state": {"learning_trail": [ TRUNCATED'
    path.write_text(corrupt, encoding="utf-8")
    calls = []

    result = soul_map_io.write_soul_map(lambda blob: calls.append(blob) or blob.update(x=1), str(path))

    assert path.read_text(encoding="utf-8") == corrupt
    assert calls == []
    assert result == {}


def test_write_read_oserror_after_fresh_cache_keeps_all_fields(tmp_path, monkeypatch):
    from internal.store import soul_map_io

    path = tmp_path / "soul_map.json"
    full = {"soul_map_state": {"learning_trail": [{"id": 1}]}, "feedback_logs": [{"n": 1}]}
    path.write_text(json.dumps(full), encoding="utf-8")
    assert read_soul_map(str(path)) == full  # fresh cache holds the full blob

    real_open = open

    def denied_for_soul_map(file, *args, **kwargs):
        if str(file) == str(path):
            raise PermissionError("denied")
        return real_open(file, *args, **kwargs)

    monkeypatch.setattr(soul_map_io, "open", denied_for_soul_map, raising=False)
    calls = []

    result = write_soul_map(lambda blob: calls.append(blob) or blob.update(x=1), str(path))

    monkeypatch.undo()
    assert calls == []
    assert result == {}
    assert json.loads(path.read_text(encoding="utf-8")) == full


def test_write_creates_missing_file(tmp_path):
    from internal.store import soul_map_io

    path = tmp_path / "fresh" / "soul_map.json"

    soul_map_io.write_soul_map(lambda blob: blob.update(x=1), str(path))

    assert json.loads(path.read_text(encoding="utf-8")) == {"x": 1}


def test_cache_refresh_failure_after_commit_still_reports_success(tmp_path, monkeypatch, caplog):
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
    monkeypatch.undo()  # the read below must not hit the patched _cache_put
    # A stale cache entry would return {"kept": 1} here. The failed refresh must not leave one.
    assert read_soul_map(str(path), copy_blob=False) == {"kept": 2}
    assert "cache refresh failed after commit" in caplog.text
