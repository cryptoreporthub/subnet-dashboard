"""Shortlist attach rules on HOLD vs LONG days."""

from internal.learning.dpick_shortlist import attach_shortlist_to_daily_pick


def _sample_subnets():
    return [
        {"netuid": 1, "name": "Alpha", "price": 1.0, "volume": 8000, "status": "active"},
        {"netuid": 2, "name": "Beta", "price": 1.0, "volume": 7000, "status": "active"},
        {"netuid": 3, "name": "Gamma", "price": 1.0, "volume": 6000, "status": "active"},
    ]


def test_hold_day_allows_single_alternative(monkeypatch):
    monkeypatch.setattr(
        "internal.learning.dpick_shortlist.build_deliberation_shortlist",
        lambda subnets, market_context, daily_payload: {
            "alternatives": [
                {
                    "netuid": 2,
                    "name": "Beta",
                    "conviction": 38,
                    "why_not": "Below gate",
                    "expert_contributions": {},
                }
            ],
            "total_considered": 3,
        },
    )
    out = attach_shortlist_to_daily_pick(
        {"action": "HOLD", "candidate": {"subnet": {"netuid": 1, "name": "Alpha"}}},
        _sample_subnets(),
        {},
    )
    assert len(out["shortlist"]) == 1


def test_long_day_still_needs_two_alternatives(monkeypatch):
    monkeypatch.setattr(
        "internal.learning.dpick_shortlist.build_deliberation_shortlist",
        lambda subnets, market_context, daily_payload: {
            "alternatives": [
                {
                    "netuid": 2,
                    "name": "Beta",
                    "conviction": 38,
                    "why_not": "Below gate",
                    "expert_contributions": {},
                }
            ],
            "total_considered": 3,
        },
    )
    out = attach_shortlist_to_daily_pick(
        {"action": "LONG", "pick": {"subnet": {"netuid": 1, "name": "Alpha"}}},
        _sample_subnets(),
        {},
    )
    assert out["shortlist"] == []
