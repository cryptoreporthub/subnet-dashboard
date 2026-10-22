import json
import os
import shutil

import pytest

from internal.council import score_snapshots as snaps
from tests.score_snapshot_testutil import complete_snapshot_payload

SEED = os.path.join("data_seeds", "score_snapshots.json")


@pytest.fixture(autouse=True)
def _paths(tmp_path, monkeypatch):
    if not os.path.isfile(SEED):
        pytest.skip("seed not generated in this checkout")
    shutil.copy(SEED, tmp_path / "seed.json")
    monkeypatch.setattr(snaps, "SCORE_SNAPSHOTS_PATH", str(tmp_path / "volume.json"))
    monkeypatch.setattr(snaps, "SCORE_SNAPSHOT_SEED_PATH", str(tmp_path / "seed.json"))
    monkeypatch.setenv("SCORE_SNAPSHOT_CYCLE_PATH", str(tmp_path / "cycle.json"))


def _bad(mutate):
    payload = complete_snapshot_payload(day_rows=[{"netuid": 1, "total_score": 5.0}])
    mutate(payload)
    return payload


BAD_SHAPES = {
    "expected_null": lambda p: p["coverage"]["day"].update(expected=[None]),
    "expected_text": lambda p: p["coverage"]["day"].update(expected=["abc"]),
    "row_netuid_text": lambda p: p.update(day=[{"netuid": "x", "total_score": 1.0}]),
    "row_netuid_null": lambda p: p.update(day=[{"netuid": None, "total_score": 1.0}]),
    "membership_text": lambda p: p["coverage"].update(day={}, membership={"expected_netuids": ["7", "x"]}),
}


@pytest.mark.parametrize("name", sorted(BAD_SHAPES))
def test_a_malformed_volume_file_is_incomplete_and_the_seed_is_served(name, tmp_path):
    payload = _bad(BAD_SHAPES[name])
    (tmp_path / "volume.json").write_text(json.dumps(payload), encoding="utf-8")
    served = snaps.read_served_snapshot()
    assert served.state is snaps.ServedState.SEED
    picks = snaps.build_top_picks_from_snapshot(None)
    assert picks is not None and picks["day_picks"]


@pytest.mark.parametrize("name", sorted(BAD_SHAPES))
def test_publish_refuses_a_malformed_snapshot_instead_of_raising(name, tmp_path):
    payload = _bad(BAD_SHAPES[name])
    result = snaps.publish_complete_snapshot(payload, snaps.SCORE_SNAPSHOTS_PATH)
    assert result.get("published") is False
    assert result.get("refused") == "incomplete"
