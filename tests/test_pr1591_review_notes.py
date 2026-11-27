import os

from internal.council import pump_overlay
from internal.file_utils import safe_write_json
from internal.pump import state


def test_readonly_ladder_does_not_reuse_a_different_loader(tmp_path, monkeypatch):
    ladder_path = tmp_path / "pump_ladder.json"
    ladder_path.write_text('{"subnets": {}}', encoding="utf-8")
    monkeypatch.setattr(state, "_resolve_path", lambda path=None: str(ladder_path))
    monkeypatch.setattr(pump_overlay, "_ladder_memo", {"key": None, "data": None})
    first = {"subnets": {"8": {"phase": "ACCUMULATING", "marker": "first"}}}
    second = {"subnets": {"8": {"phase": "PUMPING", "marker": "second"}}}
    monkeypatch.setattr(state, "load_state", lambda path=None: first)

    assert pump_overlay.pump_ladder_entry(8) == first["subnets"]["8"]

    monkeypatch.setattr(state, "load_state", lambda path=None: second)

    assert pump_overlay.pump_ladder_entry(8) == second["subnets"]["8"]


def test_readonly_ladder_does_not_cache_when_file_is_absent(tmp_path, monkeypatch):
    ladder_path = tmp_path / "missing-pump-ladder.json"
    monkeypatch.setattr(state, "_resolve_path", lambda path=None: str(ladder_path))
    monkeypatch.setattr(pump_overlay, "_ladder_memo", {"key": None, "data": None})
    first = {"subnets": {"8": {"phase": "ACCUMULATING", "marker": "first"}}}
    second = {"subnets": {"8": {"phase": "PUMPING", "marker": "second"}}}
    monkeypatch.setattr(state, "load_state", lambda path=None: first)

    assert pump_overlay.pump_ladder_entry(8) == first["subnets"]["8"]

    monkeypatch.setattr(state, "load_state", lambda path=None: second)

    assert pump_overlay.pump_ladder_entry(8) == second["subnets"]["8"]


def test_readonly_ladder_reloads_atomic_replacement_with_same_size_and_mtime(
    tmp_path, monkeypatch
):
    ladder_path = tmp_path / "pump_ladder.json"
    replacement_path = tmp_path / "replacement.json"
    monkeypatch.setattr(state, "_resolve_path", lambda path=None: str(ladder_path))
    monkeypatch.setattr(pump_overlay, "_ladder_memo", {"key": None, "data": None})
    first = {"subnets": {"8": {"phase": "ACCUMULATING", "marker": "old"}}}
    second = {"subnets": {"8": {"phase": "ACCUMULATING", "marker": "new"}}}
    safe_write_json(str(ladder_path), first)

    assert pump_overlay.pump_ladder_entry(8) == first["subnets"]["8"]
    original_stat = ladder_path.stat()

    safe_write_json(str(replacement_path), second)
    assert replacement_path.stat().st_size == original_stat.st_size
    os.utime(
        replacement_path,
        ns=(replacement_path.stat().st_atime_ns, original_stat.st_mtime_ns),
    )
    os.replace(replacement_path, ladder_path)

    replacement_stat = ladder_path.stat()
    assert replacement_stat.st_size == original_stat.st_size
    assert replacement_stat.st_mtime_ns == original_stat.st_mtime_ns
    assert pump_overlay.pump_ladder_entry(8) == second["subnets"]["8"]
