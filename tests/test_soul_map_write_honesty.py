"""Unit 1 soul-map write honesty (issue #1559)."""

from __future__ import annotations

import json
import threading
import time
from contextlib import contextmanager

import pytest

import internal.store.soul_map_io as soul_map_io
from internal.store.soul_map_io import (
    SoulMapLockWaitTimeout,
    WriteOutcome,
    read_soul_map,
    write_soul_map,
)


def test_transient_read_does_not_overwrite_file(tmp_path, monkeypatch):
    soul_path = tmp_path / "soul_map.json"
    payload = {"healthy": True, "n": 1}
    soul_path.write_text(json.dumps(payload), encoding="utf-8")
    before = soul_path.read_bytes()
    real_load = json.loads

    def boom_once(raw, *args, **kwargs):
        if not hasattr(boom_once, "called"):
            boom_once.called = True
            raise MemoryError("simulated pressure")
        return real_load(raw, *args, **kwargs)

    monkeypatch.setattr(json, "loads", boom_once)
    result = write_soul_map(
        lambda blob: blob.__setitem__("n", 99),
        path=str(soul_path),
        raise_on_lock_timeout=False,
    )
    assert result.outcome is WriteOutcome.READ_FAILED
    assert result.blob is None
    assert soul_path.read_bytes() == before


def test_declined_returns_prior_blob_not_mutated_copy(tmp_path):
    soul_path = tmp_path / "soul_map.json"
    soul_path.write_text('{"n": 1}', encoding="utf-8")
    seen = {}

    def touch(blob):
        blob["scratch"] = 1
        del blob["scratch"]
        seen["ran"] = True

    result = write_soul_map(touch, path=str(soul_path), raise_on_lock_timeout=False)
    assert result.outcome is WriteOutcome.DECLINED
    assert result.blob == {"n": 1}
    assert seen["ran"] is True


def test_declined_compares_canonical_json_not_python_equality(tmp_path):
    soul_path = tmp_path / "soul_map.json"
    soul_path.write_text('{"flag": 1}', encoding="utf-8")
    result = write_soul_map(
        lambda blob: blob.__setitem__("flag", True),
        path=str(soul_path),
        raise_on_lock_timeout=False,
    )
    assert 1 == True  # noqa: E712 — Python equality is not the declined gate
    assert result.outcome is WriteOutcome.APPLIED
    assert json.loads(soul_path.read_text(encoding="utf-8")) == {"flag": True}


def test_canonical_json_treats_one_and_true_as_distinct_values(tmp_path):
    soul_path = tmp_path / "soul_map.json"
    soul_path.write_text('{"flag": true}', encoding="utf-8")
    result = write_soul_map(
        lambda blob: blob.__setitem__("flag", 1),
        path=str(soul_path),
        raise_on_lock_timeout=False,
    )
    assert result.outcome is WriteOutcome.APPLIED
    assert json.loads(soul_path.read_text(encoding="utf-8")) == {"flag": 1}


def test_lock_timeout_returns_no_blob_and_never_reads(tmp_path, monkeypatch):
    soul_path = tmp_path / "soul_map.json"
    soul_path.write_text("{}", encoding="utf-8")

    def _never(_path):
        raise AssertionError("read_blob_checked should not run after lock timeout")

    monkeypatch.setattr(soul_map_io, "read_blob_checked", _never)

    @contextmanager
    def _instant_timeout(_path, _deadline):
        raise SoulMapLockWaitTimeout("Timed out waiting for flock test")
        yield  # pragma: no cover

    monkeypatch.setattr(soul_map_io, "_acquire_write_locks", _instant_timeout)
    result = write_soul_map(
        lambda blob: blob.__setitem__("x", 1),
        path=str(soul_path),
        raise_on_lock_timeout=False,
    )
    assert result.outcome is WriteOutcome.LOCK_WAIT_FAILED
    assert result.blob is None


def test_writers_lock_joins_five_second_deadline(tmp_path):
    soul_path = tmp_path / "soul_map.json"
    soul_path.write_text("{}", encoding="utf-8")
    started = threading.Event()
    release = threading.Event()
    writers = soul_map_io._lock_for(str(soul_path) + ".writers")

    def hold():
        with writers:
            started.set()
            release.wait(timeout=10)

    holder = threading.Thread(target=hold)
    holder.start()
    assert started.wait(timeout=2)
    t0 = time.monotonic()
    result = write_soul_map(
        lambda blob: blob.__setitem__("x", 1),
        path=str(soul_path),
        raise_on_lock_timeout=False,
    )
    elapsed = time.monotonic() - t0
    release.set()
    holder.join(timeout=5)
    assert elapsed < 6.5
    assert result.outcome is WriteOutcome.LOCK_WAIT_FAILED
    assert result.blob is None


def test_unreadable_blob_sidecar_dedupes_by_hash(tmp_path, monkeypatch):
    soul_path = tmp_path / "soul_map.json"
    soul_path.write_text("not-json", encoding="utf-8")

    first = write_soul_map(
        lambda blob: blob.__setitem__("x", 1),
        path=str(soul_path),
        raise_on_lock_timeout=False,
    )
    second = write_soul_map(
        lambda blob: blob.__setitem__("x", 2),
        path=str(soul_path),
        raise_on_lock_timeout=False,
    )
    assert first.outcome is WriteOutcome.UNREADABLE_BLOB
    assert second.outcome is WriteOutcome.UNREADABLE_BLOB
    sidecars = soul_map_io._sidecar_paths(str(soul_path))
    assert len(sidecars) == 1
    assert soul_path.read_text(encoding="utf-8") == "not-json"


def test_mutator_timeout_is_not_lock_wait_failed(tmp_path):
    soul_path = tmp_path / "soul_map.json"
    soul_path.write_text("{}", encoding="utf-8")

    def stall(_blob):
        raise TimeoutError("mutator stall")

    with pytest.raises(TimeoutError, match="mutator"):
        write_soul_map(stall, path=str(soul_path), raise_on_lock_timeout=False)
    assert soul_path.read_text(encoding="utf-8") == "{}"


def test_read_soul_map_does_not_cache_transient_empty(tmp_path, monkeypatch):
    soul_path = tmp_path / "soul_map.json"
    soul_path.write_text('{"a": 1}', encoding="utf-8")
    calls = {"n": 0}
    real = soul_map_io.read_blob_checked

    def flaky(path):
        calls["n"] += 1
        if calls["n"] == 1:
            return soul_map_io.BlobRead("transient", None, error="once")
        return real(path)

    monkeypatch.setattr(soul_map_io, "read_blob_checked", flaky)
    assert read_soul_map(str(soul_path)) == {}
    assert read_soul_map(str(soul_path)) == {"a": 1}
