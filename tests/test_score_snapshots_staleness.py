"""Late snapshot publication must not replace a newer complete build."""

from __future__ import annotations

from internal.council import score_snapshots as snaps
from tests.score_snapshot_testutil import complete_snapshot_payload


def test_late_build_does_not_clobber_fresher_snapshot(tmp_path):
    path = tmp_path / "score_snapshots.json"
    snaps.publish_complete_snapshot(
        complete_snapshot_payload(
            day_rows=[{"netuid": 2, "total_score": 20.0}],
            written_at="2026-09-22T12:00:00Z",
        ),
        str(path),
    )
    snaps.publish_complete_snapshot(
        complete_snapshot_payload(
            day_rows=[{"netuid": 1, "total_score": 1.0}],
            written_at="2026-09-22T11:00:00Z",
        ),
        str(path),
    )
    saved = snaps.load_score_snapshot(str(path))
    assert saved["day"][0]["netuid"] == 2
    assert saved["build_started_at"] == "2026-09-22T12:00:00Z"


def test_legacy_written_at_snapshot_stays_valid(tmp_path):
    path = tmp_path / "score_snapshots.json"
    snaps.publish_complete_snapshot(
        complete_snapshot_payload(
            day_rows=[{"netuid": 4, "total_score": 8.0}],
            written_at="2026-09-22T12:00:00Z",
        ),
        str(path),
    )
    ranked = snaps.rank_subnets_by_snapshot(
        [{"netuid": 4}, {"netuid": 9}],
        path=str(path),
        max_age_seconds=7200,
    )
    assert ranked is not None
    assert ranked[0]["netuid"] == 4


def test_build_stamps_start_before_scoring(monkeypatch):
    stamps = []

    def _day(sn, ctx):
        stamps.append(snaps._now_iso())
        return {"total_score": 1.0}

    monkeypatch.setattr("internal.council.state_vector.score_subnet_for_day", _day)
    monkeypatch.setattr("internal.council.state_vector.score_subnet_for_hour", _day)
    monkeypatch.setattr("internal.subnets.tradable.tradable_subnets", lambda rows: rows)
    monkeypatch.setattr(snaps, "_score_hour_enabled", lambda: False)
    out = snaps.build_full_universe_snapshot([{"netuid": 1}], {})
    assert out["build_started_at"] <= stamps[0]
    assert "written_at" in out
