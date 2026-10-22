import json

import pytest

from internal.council import score_snapshots as snaps
from tests.score_snapshot_testutil import complete_snapshot_payload


def _seed_volume(tmp_path, monkeypatch, *, complete: bool):
    path = tmp_path / "score_snapshots.json"
    rows = [{"netuid": n, "total_score": 50.0 + n} for n in range(1, 4)]
    if complete:
        payload = complete_snapshot_payload(day_rows=rows, hour_rows=rows)
    else:
        payload = {
            "written_at": snaps._now_iso(),
            "coverage": {"complete": False},
            "hour": rows,
            "day": rows,
        }
    path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(snaps, "SCORE_SNAPSHOTS_PATH", str(path))
    monkeypatch.setattr(snaps, "SCORE_SNAPSHOT_SEED_PATH", str(tmp_path / "no_seed.json"))
    monkeypatch.setattr(snaps, "SCORE_SNAPSHOT_MAX_AGE_SECONDS", 7200)


@pytest.fixture
def builds(monkeypatch):
    calls = []

    def _revive():
        calls.append(1)
        return {"revived": True}

    monkeypatch.setattr(snaps, "revive_score_snapshot_scheduler", _revive)
    return calls


def test_ensure_builds_when_the_snapshot_on_disk_is_incomplete(tmp_path, monkeypatch, builds):
    _seed_volume(tmp_path, monkeypatch, complete=False)
    out = snaps.ensure_complete_snapshot()
    assert builds == [1]
    assert out["ensured"] is True


def test_ensure_builds_when_there_is_no_snapshot(tmp_path, monkeypatch, builds):
    monkeypatch.setattr(snaps, "SCORE_SNAPSHOTS_PATH", str(tmp_path / "absent.json"))
    monkeypatch.setattr(snaps, "SCORE_SNAPSHOT_SEED_PATH", str(tmp_path / "no_seed.json"))
    snaps.ensure_complete_snapshot()
    assert builds == [1]


def test_ensure_leaves_a_complete_snapshot_alone(tmp_path, monkeypatch, builds):
    _seed_volume(tmp_path, monkeypatch, complete=True)
    out = snaps.ensure_complete_snapshot()
    assert builds == []
    assert out["ensured"] is False


def test_ensure_skips_revive_when_image_seed_is_servable(tmp_path, monkeypatch, builds):
    seed = complete_snapshot_payload(day_rows=[{"netuid": 1, "total_score": 1.0}])
    seed_path = tmp_path / "seed.json"
    seed_path.write_text(json.dumps(seed), encoding="utf-8")
    monkeypatch.setattr(snaps, "SCORE_SNAPSHOTS_PATH", str(tmp_path / "absent.json"))
    monkeypatch.setattr(snaps, "SCORE_SNAPSHOT_SEED_PATH", str(seed_path))
    out = snaps.ensure_complete_snapshot()
    assert builds == []
    assert out["ensured"] is False
