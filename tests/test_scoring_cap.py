"""Scoring universe cap — mega exclusion + mid-cap focus."""

import pytest

from internal.subnets.scoring_cap import cap_subnets_for_scoring


@pytest.fixture(autouse=True)
def _no_snapshot_rank(monkeypatch):
    """Local data/score_snapshots.json must not bypass tier logic in these tests."""
    monkeypatch.setattr(
        "internal.council.score_snapshots.rank_subnets_by_snapshot",
        lambda *args, **kwargs: None,
    )


def _mega(netuid: int, rank: int, volume: float = 1e6, name: str = "") -> dict:
    return {
        "netuid": netuid,
        "name": name or f"Mega{netuid}",
        "marketcap_rank": rank,
        "market_cap": 50e6,
        "volume": volume,
        "price": 10.0,
        "emission": 1.0,
    }


def _mid(netuid: int, rank: int, volume: float = 5_000) -> dict:
    return {
        "netuid": netuid,
        "name": f"Mid{netuid}",
        "marketcap_rank": rank,
        "market_cap": 2e6,
        "volume": volume,
        "price": 1.0,
        "emission": 0.5,
    }


def test_mega_names_excluded_from_heuristic_cap():
    """Chutes/Targon-tier ranks should not consume scoring slots without snapshot."""
    rows = [
        _mega(64, 1, name="Chutes"),
        _mega(4, 2, name="Targon"),
        _mega(51, 3, name="Lium"),
        _mega(120, 4, name="Affine"),
        _mega(5, 5, volume=1e6),
        _mega(6, 6, volume=1e6),
        _mega(7, 7, volume=1e6),
        _mega(8, 8, volume=1e6),
        _mega(9, 9, volume=1e6),
        _mega(10, 10, volume=1e6),
    ]
    rows.extend(_mid(200 + i, 40 + i, volume=8_000) for i in range(12))
    capped = cap_subnets_for_scoring(rows, limit=10)
    uids = {r["netuid"] for r in capped}
    assert uids.isdisjoint({64, 4, 51, 120, 5, 6, 7, 8, 9, 10})
    assert len(uids) == 10
    assert all(u >= 200 for u in uids)


def test_mid_beats_rank_eleven_spillover():
    rows = [
        _mega(11, 11, volume=500),
        _mid(30, 30, volume=20_000),
    ]
    capped = cap_subnets_for_scoring(rows, limit=1)
    assert capped[0]["netuid"] == 30


def test_cap_prefers_volume_over_stale_emission():
    rows = [
        {"netuid": 1, "name": "HighEmit", "emission": 99, "volume": 10, "marketcap_rank": 40},
        {
            "netuid": 2,
            "name": "Active",
            "emission": 1,
            "volume": 50_000,
            "market_cap": 2e6,
            "marketcap_rank": 45,
        },
        {"netuid": 3, "name": "Mid", "emission": 50, "volume": 100, "marketcap_rank": 50},
    ]
    capped = cap_subnets_for_scoring(rows, limit=1)
    assert capped[0]["netuid"] == 2
