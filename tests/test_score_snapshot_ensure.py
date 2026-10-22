import json

import pytest

from internal.council import score_snapshots as snaps


def _seed(tmp_path, monkeypatch, *, complete):
    path = tmp_path / "score_snapshots.json"
    rows = [{"netuid": n, "total_score": 50.0 + n} for n in range(1, 4)]
    path.write_text(
        json.dumps(
            {
                "written_at": snaps._now_iso(),
                "coverage": {"complete": complete},
                "hour": rows,
                "day": rows,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(snaps, "SCORE_SNAPSHOTS_PATH", str(path))
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
    _seed(tmp_path, monkeypatch, complete=False)
    out = snaps.ensure_complete_snapshot()
    assert builds == [1]
    assert out["ensured"] is True


def test_ensure_builds_when_there_is_no_snapshot(tmp_path, monkeypatch, builds):
    monkeypatch.setattr(snaps, "SCORE_SNAPSHOTS_PATH", str(tmp_path / "absent.json"))
    snaps.ensure_complete_snapshot()
    assert builds == [1]


def test_ensure_leaves_a_complete_snapshot_alone(tmp_path, monkeypatch, builds):
    _seed(tmp_path, monkeypatch, complete=True)
    out = snaps.ensure_complete_snapshot()
    assert builds == []
    assert out["ensured"] is False
