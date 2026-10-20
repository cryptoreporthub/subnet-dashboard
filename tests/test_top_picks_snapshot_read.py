"""Request-path top picks must read score_snapshots.json, not score the universe."""

import json
import time

import pytest


def test_build_top_picks_from_snapshot(tmp_path, monkeypatch):
    from internal.council import score_snapshots as snaps

    snap_path = tmp_path / "score_snapshots.json"
    payload = {
        "written_at": "2026-10-17T00:00:00Z",
        "hour": [{"netuid": 2, "total_score": 90.0, "name": "A"}],
        "day": [
            {"netuid": 2, "total_score": 90.0, "name": "A"},
            {"netuid": 3, "total_score": 80.0, "name": "B"},
        ],
    }
    snap_path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(snaps, "SCORE_SNAPSHOTS_PATH", str(snap_path))
    monkeypatch.setattr(snaps, "SCORE_SNAPSHOT_MAX_AGE_SECONDS", 7200)

    subnets = [
        {"netuid": 2, "name": "A", "symbol": "A", "emission": 1.0},
        {"netuid": 3, "name": "B", "symbol": "B", "emission": 0.5},
    ]
    out = snaps.build_top_picks_from_snapshot(subnets)
    assert out is not None
    assert out["hour_picks"][0]["netuid"] == 2
    assert out["day_picks"][0]["score"] == 90.0
    assert out["meta"]["source"] == "score_snapshot"


def test_build_top_picks_server_uses_snapshot_not_score_universe(tmp_path, monkeypatch):
    from internal.council import score_snapshots as snaps
    from server import _build_top_picks

    snap_path = tmp_path / "score_snapshots.json"
    snap_path.write_text(
        json.dumps(
            {
                "hour": [{"netuid": 5, "total_score": 77.0}],
                "day": [{"netuid": 5, "total_score": 77.0}],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(snaps, "SCORE_SNAPSHOTS_PATH", str(snap_path))
    monkeypatch.setattr(snaps, "SCORE_SNAPSHOT_MAX_AGE_SECONDS", 7200)
    monkeypatch.setattr(
        "server._get_subnets_with_source",
        lambda timeout=4.0: ([{"netuid": 5, "name": "X"}], "test"),
    )

    def _boom(*_a, **_k):
        raise AssertionError("score_universe must not run on request path")

    monkeypatch.setattr("internal.council.score_cache.score_universe", _boom)

    payload = _build_top_picks()
    assert payload["day_picks"][0]["netuid"] == 5
    assert payload.get("meta", {}).get("source") == "score_snapshot"


def _write_snapshot(tmp_path, monkeypatch, day_rows):
    from internal.council import score_snapshots as snaps

    snap_path = tmp_path / "score_snapshots.json"
    snap_path.write_text(
        json.dumps({"written_at": "2026-10-17T00:00:00Z", "hour": day_rows, "day": day_rows}),
        encoding="utf-8",
    )
    monkeypatch.setattr(snaps, "SCORE_SNAPSHOTS_PATH", str(snap_path))
    monkeypatch.setattr(snaps, "SCORE_SNAPSHOT_MAX_AGE_SECONDS", 7200)
    return snaps


def test_snapshot_picks_carry_the_real_confidence_not_the_score(tmp_path, monkeypatch):
    snaps = _write_snapshot(
        tmp_path,
        monkeypatch,
        [
            {
                "netuid": 2,
                "total_score": 66.35,
                "name": "A",
                "confidence": 0.53,
                "scenario_tags": {"fallback": "highest-emission"},
            }
        ],
    )
    out = snaps.build_top_picks_from_snapshot([{"netuid": 2, "name": "A", "symbol": "A"}])
    pick = out["day_picks"][0]
    assert 0 <= pick["confidence"] <= 1
    assert pick["confidence"] == 0.53
    assert pick["confidence"] != pick["score"]
    assert pick["scenario_tags"] == {"fallback": "highest-emission"}

    scored = snaps.day_scored_from_snapshot([{"netuid": 2, "name": "A"}])
    assert scored[0]["score"]["confidence"] == 0.53
    assert scored[0]["score"]["scenario_tags"] == {"fallback": "highest-emission"}


def test_snapshot_pick_omits_confidence_when_the_row_has_none(tmp_path, monkeypatch):
    snaps = _write_snapshot(tmp_path, monkeypatch, [{"netuid": 2, "total_score": 66.35, "name": "A"}])
    out = snaps.build_top_picks_from_snapshot([{"netuid": 2, "name": "A", "symbol": "A"}])
    assert "confidence" not in out["day_picks"][0]
    scored = snaps.day_scored_from_snapshot([{"netuid": 2, "name": "A"}])
    assert "confidence" not in scored[0]["score"]


def test_built_snapshot_rows_carry_confidence_between_zero_and_one():
    from internal.council import score_snapshots as snaps

    subnets = [
        {"netuid": n, "name": f"S{n}", "price": 1.0, "price_change_24h": 1.0, "emission": 1.0, "volume": 1000.0}
        for n in (1, 2, 3)
    ]
    snap = snaps.build_full_universe_snapshot(subnets, {}, score_hour=False)
    assert snap["day"], "expected scored day rows"
    for row in snap["day"]:
        assert 0 <= row["confidence"] <= 1
        assert row["confidence"] != row["total_score"]
        assert isinstance(row["scenario_tags"], dict)
