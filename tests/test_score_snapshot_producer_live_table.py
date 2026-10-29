"""PR-A live-table harness: boot row must be safe on a real DATA_DIR and see the armed scheduler."""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import pytest

from internal.council import score_snapshots as snaps

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "score_snapshot_producer_mc_live_table.py"


@pytest.fixture
def live_table(monkeypatch):
    for key, value in (
        ("DISABLE_BACKGROUND_SCANS", "1"),
        ("FINNEY_RPC_URL", "http://finney.invalid"),
        ("BLOCKMACHINE_RPC_URL", "http://blockmachine.invalid"),
    ):
        monkeypatch.setenv(key, value)
    # The harness mutates os.environ and replaces module attributes without restoring
    # them; give it a private env copy and let monkeypatch put back what it swaps.
    monkeypatch.setattr(os, "environ", os.environ.copy())
    import internal.background_boot as boot
    import internal.freshness as freshness

    for mod in (boot, freshness):
        for name, value in list(vars(mod).items()):
            monkeypatch.setattr(mod, name, value)
    spec = importlib.util.spec_from_file_location("score_snapshot_producer_mc_live_table", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)  # @dataclass resolves its module here
    spec.loader.exec_module(module)
    yield module
    snaps.stop_score_snapshot_scheduler()


def test_boot_row_never_touches_existing_data_dir_soul_map(live_table, tmp_path, monkeypatch):
    volume = tmp_path / "volume"
    volume.mkdir()
    soul = volume / "soul_map.json"
    soul.write_text('{"keep": "me"}', encoding="utf-8")
    monkeypatch.setenv("DATA_DIR", str(volume))

    live_table._boot_producer_starts(live_table._fly_worker_entrypoint_env())

    assert soul.read_text(encoding="utf-8") == '{"keep": "me"}'
    assert sorted(p.name for p in volume.iterdir()) == ["soul_map.json"]
    assert os.environ["DATA_DIR"] == str(volume)


def test_boot_row_observes_deferred_scheduler_armed(live_table):
    armed, jobs = live_table._boot_producer_starts(live_table._fly_worker_entrypoint_env())

    assert armed is True
    assert jobs == "score-snapshots"
