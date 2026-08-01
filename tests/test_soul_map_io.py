"""Tests for thread-safe soul_map read-modify-write gateway."""

from __future__ import annotations

import json
import threading
from pathlib import Path

import internal.store.soul_map_io as soul_map_io
from internal.council.mindmap_bridge import MindmapBridge
from internal.store.soul_map_io import read_soul_map, write_soul_map


def test_write_soul_map_concurrent_increments_no_lost_updates(tmp_path):
    soul_path = tmp_path / "soul_map.json"

    def increment():
        for _ in range(50):
            write_soul_map(
                lambda blob: blob.__setitem__(
                    "counter", blob.get("counter", 0) + 1
                ),
                path=str(soul_path),
            )

    threads = [threading.Thread(target=increment) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert read_soul_map(str(soul_path))["counter"] == 100


def test_write_soul_map_is_atomic_on_success(tmp_path, monkeypatch):
    soul_path = tmp_path / "soul_map.json"
    write_soul_map(lambda blob: blob.update({"alpha": 1, "beta": 2}), path=str(soul_path))
    write_soul_map(lambda blob: blob.__setitem__("gamma", 3), path=str(soul_path))

    with open(soul_path, "r") as f:
        data = json.load(f)

    assert data == {"alpha": 1, "beta": 2, "gamma": 3}


def test_read_soul_map_missing_file_returns_empty_dict(tmp_path):
    missing = tmp_path / "does_not_exist.json"
    assert read_soul_map(str(missing)) == {}


def test_mindmap_bridge_save_preserves_unrelated_top_level_keys(tmp_path):
    soul_path = tmp_path / "soul_map.json"
    with open(soul_path, "w") as f:
        json.dump({"adversarial_state": {"foo": 1}, "soul_map_state": {}}, f)

    bridge = MindmapBridge(persistence_path=str(soul_path))
    bridge.append_learning_trail({"event_type": "test_event"})

    with open(soul_path, "r") as f:
        data = json.load(f)

    assert data["adversarial_state"]["foo"] == 1
    trail = data["soul_map_state"]["learning_trail"]
    assert any(entry.get("event_type") == "test_event" for entry in trail)


def test_write_then_read_sees_new_data_immediately_after_ttl_expiry(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(soul_map_io, "_CACHE_TTL", 0)
    soul_path = tmp_path / "soul_map.json"
    write_soul_map(lambda blob: blob.update({"v": 1}), path=str(soul_path))
    write_soul_map(lambda blob: blob.__setitem__("v", 2), path=str(soul_path))
    assert read_soul_map(str(soul_path))["v"] == 2


def test_read_soul_map_returns_independent_deep_copies(tmp_path):
    soul_path = tmp_path / "soul_map.json"
    write_soul_map(lambda blob: blob.update({"seed": True}), path=str(soul_path))

    first = read_soul_map(str(soul_path))
    second = read_soul_map(str(soul_path))
    first["injected"] = "poison"

    third = read_soul_map(str(soul_path))
    assert "injected" not in third
    assert second == {"seed": True}


def test_soul_map_cache_is_keyed_per_path(tmp_path):
    path_a = tmp_path / "a.json"
    path_b = tmp_path / "b.json"
    write_soul_map(lambda blob: blob.update({"file": "a"}), path=str(path_a))
    write_soul_map(lambda blob: blob.update({"file": "b"}), path=str(path_b))

    assert read_soul_map(str(path_a)) == {"file": "a"}
    assert read_soul_map(str(path_b)) == {"file": "b"}


def test_read_soul_map_cache_skips_disk_within_ttl(monkeypatch, tmp_path):
    soul_path = tmp_path / "soul_map.json"
    with open(soul_path, "w") as f:
        json.dump({"cached": True}, f)

    original = soul_map_io._read_blob
    call_count = {"n": 0}

    def counting(*a, **kw):
        call_count["n"] += 1
        return original(*a, **kw)

    monkeypatch.setattr(soul_map_io, "_read_blob", counting)

    read_soul_map(str(soul_path))
    read_soul_map(str(soul_path))
    read_soul_map(str(soul_path))

    assert call_count["n"] == 1


def test_write_soul_map_refreshes_cache_without_stale_hit(tmp_path):
    soul_path = tmp_path / "soul_map.json"
    write_soul_map(lambda blob: blob.update({"v": 1}), path=str(soul_path))
    write_soul_map(lambda blob: blob.__setitem__("v", 2), path=str(soul_path))
    assert read_soul_map(str(soul_path))["v"] == 2


def test_write_soul_map_failed_io_does_not_poison_cache(monkeypatch, tmp_path):
    soul_path = tmp_path / "soul_map.json"
    write_soul_map(lambda blob: blob.update({"v": 1}), path=str(soul_path))

    def fail_replace(*a, **kw):
        raise OSError("simulated failure")

    monkeypatch.setattr(soul_map_io.os, "replace", fail_replace)

    write_soul_map(lambda blob: blob.__setitem__("v", 2), path=str(soul_path))
    assert read_soul_map(str(soul_path))["v"] == 1
