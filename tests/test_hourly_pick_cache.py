"""Hourly pick TTL cache."""

from __future__ import annotations

from unittest.mock import MagicMock

from internal.council.hourly_pick import clear_hourly_pick_cache, select_hourly_pick


def _subnet(netuid: int, name: str = "Test") -> dict:
    return {
        "netuid": netuid,
        "name": name,
        "emission": 1.0,
        "price_change_24h": 1.0,
        "volume": 1000,
    }


def test_select_hourly_pick_caches_within_ttl(monkeypatch):
    clear_hourly_pick_cache()
    calls = {"n": 0}

    def hour(sn, ctx):
        calls["n"] += 1
        return {
            "total_score": float(sn["netuid"]),
            "confidence": 0.5,
            "expert_contributions": {},
            "scenario_tags": {},
        }

    monkeypatch.setattr("internal.council.hourly_pick.score_subnet_for_hour", hour)
    monkeypatch.setattr(
        "internal.council.hourly_pick.audit_daily_pick",
        lambda candidate, subnets: {
            "approved": True,
            "concerns": [],
            "adjusted_confidence": 0.5,
        },
    )
    monkeypatch.setattr(
        "internal.council.hourly_pick.attach_council_prediction",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "internal.council.hourly_pick.unpack_score_learning_fields",
        lambda score: {
            "signal_impact": None,
            "signal_contributions": None,
            "active_signals": [],
        },
    )
    monkeypatch.setattr("internal.council.hourly_pick.pick_reasons", lambda *args: [])

    subnets = [_subnet(1), _subnet(2)]
    ctx = {"tao_change_24h": 0.0, "weights": {"quant": 0.3}}

    first = select_hourly_pick(subnets, ctx)
    second = select_hourly_pick(subnets, ctx)

    assert first["subnet"]["netuid"] == second["subnet"]["netuid"]
    assert calls["n"] == 2


def test_select_hourly_pick_cache_invalidates_on_universe_change(monkeypatch):
    clear_hourly_pick_cache()
    hour = MagicMock(
        side_effect=lambda sn, ctx: {
            "total_score": float(sn["netuid"]),
            "confidence": 0.5,
            "expert_contributions": {},
            "scenario_tags": {},
        }
    )
    monkeypatch.setattr("internal.council.hourly_pick.score_subnet_for_hour", hour)
    monkeypatch.setattr(
        "internal.council.hourly_pick.audit_daily_pick",
        lambda candidate, subnets: {
            "approved": True,
            "concerns": [],
            "adjusted_confidence": 0.5,
        },
    )
    monkeypatch.setattr(
        "internal.council.hourly_pick.attach_council_prediction",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "internal.council.hourly_pick.unpack_score_learning_fields",
        lambda score: {
            "signal_impact": None,
            "signal_contributions": None,
            "active_signals": [],
        },
    )
    monkeypatch.setattr("internal.council.hourly_pick.pick_reasons", lambda *args: [])

    select_hourly_pick([_subnet(1)], {"weights": {}})
    select_hourly_pick([_subnet(2)], {"weights": {}})

    assert hour.call_count == 2
