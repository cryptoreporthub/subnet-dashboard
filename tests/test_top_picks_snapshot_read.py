"""Request-path top picks must read score_snapshots.json, not score the universe."""

import json

import pytest

from tests.score_snapshot_testutil import complete_snapshot_payload


@pytest.fixture(autouse=True)
def _isolate_snapshot_paths(tmp_path, monkeypatch):
    from internal.council import score_snapshots as snaps

    monkeypatch.setattr(snaps, "SCORE_SNAPSHOTS_PATH", str(tmp_path / "volume.json"))
    monkeypatch.setattr(snaps, "SCORE_SNAPSHOT_SEED_PATH", str(tmp_path / "no_seed.json"))


def _write_volume(tmp_path, payload):
    path = tmp_path / "volume.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_build_top_picks_from_snapshot(tmp_path, monkeypatch):
    from internal.council import score_snapshots as snaps

    day = [
        {"netuid": 2, "total_score": 90.0, "name": "A"},
        {"netuid": 3, "total_score": 80.0, "name": "B"},
    ]
    _write_volume(tmp_path, complete_snapshot_payload(day_rows=day))
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
    assert out["meta"]["snapshot_state"] in ("fresh", "aged")


@pytest.mark.parametrize(
    "extra",
    [{}, {"coverage": {"complete": False, "capture_reason": "capture_timeout"}}],
    ids=["no_coverage_block", "incomplete_capture"],
)
def test_build_top_picks_never_serves_incomplete_volume_without_seed(tmp_path, extra):
    from internal.council import score_snapshots as snaps

    rows = [{"netuid": 2, "total_score": 90.0, "name": "A"}]
    _write_volume(
        tmp_path,
        {"written_at": "2026-10-17T00:00:00Z", "hour": rows, "day": rows, **extra},
    )
    subnets = [{"netuid": 2, "name": "A", "symbol": "A", "emission": 1.0}]
    assert snaps.build_top_picks_from_snapshot(subnets) is None


def test_incomplete_volume_falls_back_to_compatible_seed(tmp_path, monkeypatch):
    from internal.council import score_snapshots as snaps

    seed = complete_snapshot_payload(
        day_rows=[{"netuid": 9, "total_score": 50.0, "name": "Seed"}]
    )
    (tmp_path / "no_seed.json").write_text(json.dumps(seed), encoding="utf-8")
    monkeypatch.setattr(snaps, "SCORE_SNAPSHOT_SEED_PATH", str(tmp_path / "no_seed.json"))
    _write_volume(
        tmp_path,
        {
            "written_at": "2026-10-17T00:00:00Z",
            "coverage": {"complete": False},
            "day": [{"netuid": 2, "total_score": 1.0}],
            "hour": [],
        },
    )
    out = snaps.build_top_picks_from_snapshot([])
    assert out is not None
    assert out["day_picks"][0]["netuid"] == 9
    assert out["meta"]["snapshot_state"] == "seed"


@pytest.mark.parametrize("reader", ["build_top_picks", "day_scored", "rank"])
def test_scored_readers_serve_complete_volume(tmp_path, reader):
    from internal.council import score_snapshots as snaps

    rows = [{"netuid": 2, "total_score": 90.0, "name": "A"}]
    _write_volume(tmp_path, complete_snapshot_payload(day_rows=rows))
    subnets = [{"netuid": 2, "name": "A", "symbol": "A"}]
    read = {
        "build_top_picks": snaps.build_top_picks_from_snapshot,
        "day_scored": snaps.day_scored_from_snapshot,
        "rank": snaps.rank_subnets_by_snapshot,
    }[reader]
    assert read(subnets) is not None


def test_deliberation_shortlist_says_pending_for_partial_snapshot(tmp_path):
    from internal.learning.dpick_shortlist import build_deliberation_shortlist

    _write_volume(
        tmp_path,
        {
            "written_at": "2026-10-17T00:00:00Z",
            "coverage": {"complete": False, "capture_reason": "capture_timeout"},
            "hour": [],
            "day": [{"netuid": 2, "total_score": 90.0, "name": "A"}],
        },
    )
    out = build_deliberation_shortlist([{"netuid": 2, "name": "A", "symbol": "A", "emission": 1.0}])
    assert out.get("status") == "pending_snapshot"
    assert out["total_considered"] == 0


def test_build_top_picks_server_uses_snapshot_not_score_universe(tmp_path, monkeypatch):
    from server import _build_top_picks

    _write_volume(
        tmp_path,
        complete_snapshot_payload(
            day_rows=[{"netuid": 5, "total_score": 77.0, "name": "X"}],
            hour_rows=[{"netuid": 5, "total_score": 77.0, "name": "X"}],
        ),
    )
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


def _write_snapshot(tmp_path, day_rows):
    from internal.council import score_snapshots as snaps

    _write_volume(tmp_path, complete_snapshot_payload(day_rows=day_rows))
    return snaps


def test_snapshot_picks_carry_the_real_confidence_not_the_score(tmp_path):
    snaps = _write_snapshot(
        tmp_path,
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


def test_snapshot_pick_omits_confidence_when_the_row_has_none(tmp_path):
    snaps = _write_snapshot(tmp_path, [{"netuid": 2, "total_score": 66.35, "name": "A"}])
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


def test_built_snapshot_hour_rows_carry_confidence_when_hour_scoring_is_on():
    from internal.council import score_snapshots as snaps

    subnets = [
        {"netuid": n, "name": f"S{n}", "price": 1.0, "price_change_24h": 1.0, "emission": 1.0, "volume": 1000.0}
        for n in (1, 2, 3)
    ]
    snap = snaps.build_full_universe_snapshot(subnets, {}, score_hour=True)
    assert snap["hour"], "expected scored hour rows"
    for row in snap["hour"]:
        assert 0 <= row["confidence"] <= 1
        assert row["confidence"] != row["total_score"]


@pytest.mark.parametrize("bad", [66.35, -0.1, 1.01, True, "0.5", None])
def test_confidence_outside_zero_to_one_is_left_out(bad):
    from internal.council import score_snapshots as snaps

    assert "confidence" not in snaps._confidence_fields({"confidence": bad})


def test_alternative_conviction_does_not_fall_back_to_the_score(monkeypatch):
    from internal.learning.dpick_shortlist import build_deliberation_shortlist

    subnets = [{"netuid": n, "name": f"S{n}", "price": 1.0, "volume": 1000.0} for n in (1, 2, 3)]
    scored = [
        {"subnet": sn, "score": {"total_score": 66.0, "expert_contributions": {}}} for sn in subnets
    ]
    monkeypatch.setattr(
        "internal.council.score_snapshots.day_scored_from_snapshot", lambda _subnets: scored
    )
    out = build_deliberation_shortlist(subnets, {}, {"pick": None})
    assert out["alternatives"], "expected alternatives"
    assert all(alt["conviction"] == 0 for alt in out["alternatives"])
