"""SimiLeads compute tests."""

from __future__ import annotations

from internal.analytics.simileads import build_simileads_rows


def test_simileads_ranks_score_up_price_flat():
    subnets = [
        {"netuid": 1, "name": "Alpha", "price_change_24h": 0.4},
        {"netuid": 2, "name": "Beta", "price_change_24h": -1.2},
        {"netuid": 3, "name": "Gamma", "price_change_24h": 5.0},
    ]
    picks = [
        {"netuid": 1, "name": "Alpha", "conviction_delta": 8},
        {"netuid": 2, "name": "Beta", "conviction_delta": 6},
        {"netuid": 3, "name": "Gamma", "conviction_delta": 10},
    ]
    rows = build_simileads_rows(subnets, picks, limit=3)
    assert len(rows) == 2
    assert rows[0]["netuid"] == 1
    assert rows[0]["lag_index"] == 7.6
    assert rows[1]["netuid"] == 2


def test_simileads_honest_empty_when_no_divergence():
    subnets = [{"netuid": 1, "price_change_24h": 8.0}]
    picks = [{"netuid": 1, "conviction_delta": 5}]
    assert build_simileads_rows(subnets, picks) == []
