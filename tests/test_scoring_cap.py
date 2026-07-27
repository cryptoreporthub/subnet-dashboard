"""Scoring universe cap — majors budget + mid-cap focus."""

import pytest

from internal.subnets.scoring_cap import cap_subnets_for_scoring


@pytest.fixture(autouse=True)
def _no_snapshot_rank(monkeypatch):
    """Local data/score_snapshots.json must not bypass tier logic in these tests."""
    monkeypatch.setattr(
        "internal.council.score_snapshots.rank_subnets_by_snapshot",
        lambda *args, **kwargs: None,
    )


def _mega(netuid: int, rank: int, volume: float = 1e6) -> dict:
    return {
        "netuid": netuid,
        "name": f"Mega{netuid}",
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


def test_majors_capped_rest_prefers_mid_band():
    rows = [_mega(i, i, volume=1e6) for i in range(1, 11)]
    rows.append(_mid(50, 40, volume=8_000))
    rows.append(_mid(51, 55, volume=7_000))
    capped = cap_subnets_for_scoring(rows, limit=10)
    uids = [r["netuid"] for r in capped]
    assert len(uids) == 10
    # Up to 8 mega names, not all 10 megas
    mega_count = sum(1 for u in uids if u <= 10)
    assert mega_count <= 8
    # Mid-cap focus rows must appear
    assert 50 in uids
    assert 51 in uids


def test_activity_within_mid_beats_mega_spillover():
    rows = [
        _mega(1, 1),
        _mega(12, 12, volume=500),  # large-cap spillover, weak activity
        _mid(30, 30, volume=20_000),
    ]
    capped = cap_subnets_for_scoring(rows, limit=2)
    uids = [r["netuid"] for r in capped]
    assert uids[0] == 1  # major slot
    assert uids[1] == 30  # mid band beats rank-12 spillover


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
