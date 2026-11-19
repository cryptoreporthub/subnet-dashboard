from internal.council import pump_overlay
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
