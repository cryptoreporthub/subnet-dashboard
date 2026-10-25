"""build_image_seed_snapshot must leave process-wide config as it found it (MC act-on 7, #1484)."""

import os

import pytest

from internal.council import build_seed_snapshot as seed_build
from internal.council import score_snapshots as snaps
from tests.score_snapshot_testutil import chain_read

CHAIN = chain_read((1, 2))
ROWS = [{"netuid": n, "name": f"S{n}", "price": 1.0} for n in (1, 2)]


@pytest.fixture
def known_state(monkeypatch, tmp_path):
    monkeypatch.setenv("SCORE_SNAPSHOT_CYCLE_PATH", str(tmp_path / "caller_cycle.json"))
    monkeypatch.delenv("SCORE_SNAPSHOT_REGISTRY_ONLY", raising=False)
    monkeypatch.setattr(snaps, "SCORE_SNAPSHOTS_PATH", str(tmp_path / "caller_volume.json"))
    monkeypatch.setattr(snaps, "SCORE_SNAPSHOT_SEED_PATH", str(tmp_path / "caller_seed.json"))
    monkeypatch.setattr(seed_build, "build_authoritative_hydrate_rows", lambda ids: (list(ROWS), {}))
    return {
        "cycle": os.environ["SCORE_SNAPSHOT_CYCLE_PATH"],
        "volume": snaps.SCORE_SNAPSHOTS_PATH,
        "seed": snaps.SCORE_SNAPSHOT_SEED_PATH,
    }


def _assert_restored(state):
    assert os.environ["SCORE_SNAPSHOT_CYCLE_PATH"] == state["cycle"]
    assert "SCORE_SNAPSHOT_REGISTRY_ONLY" not in os.environ
    assert snaps.SCORE_SNAPSHOTS_PATH == state["volume"]
    assert snaps.SCORE_SNAPSHOT_SEED_PATH == state["seed"]


def test_state_is_restored_after_a_build(known_state, monkeypatch, tmp_path):
    monkeypatch.setattr(snaps, "write_full_universe_snapshot", lambda: {"published": False})
    seed_build.build_image_seed_snapshot(
        chain=CHAIN, volume_path=str(tmp_path / "v.json"), cycle_path=str(tmp_path / "c.json")
    )
    _assert_restored(known_state)


def test_state_is_restored_when_the_build_raises(known_state, monkeypatch, tmp_path):
    def boom():
        raise RuntimeError("scorer exploded")

    monkeypatch.setattr(snaps, "write_full_universe_snapshot", boom)
    with pytest.raises(RuntimeError, match="scorer exploded"):
        seed_build.build_image_seed_snapshot(
            chain=CHAIN, volume_path=str(tmp_path / "v.json"), cycle_path=str(tmp_path / "c.json")
        )
    _assert_restored(known_state)
