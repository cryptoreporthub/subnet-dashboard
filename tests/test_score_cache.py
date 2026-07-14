"""Score cache TTL and deduplication."""

from __future__ import annotations

from unittest.mock import MagicMock

from internal.council.score_cache import clear_score_cache, score_universe


def test_score_universe_caches_within_ttl(monkeypatch):
    clear_score_cache()
    calls = {"n": 0}

    def hour(sn, ctx):
        calls["n"] += 1
        return {"total_score": float(sn["netuid"])}

    def day(sn, ctx):
        return {"total_score": 0.0}

    subnets = [{"netuid": 1, "name": "A"}, {"netuid": 2, "name": "B"}]
    ctx = {"tao_change_24h": 0.0, "weights": {"quant": 0.3}}

    h1, d1 = score_universe(subnets, ctx, score_hour=hour, score_day=day)
    h2, d2 = score_universe(subnets, ctx, score_hour=hour, score_day=day)

    assert len(h1) == 2
    assert h1 is h2
    assert calls["n"] == 2


def test_score_universe_invalidates_on_universe_change():
    clear_score_cache()
    hour = MagicMock(side_effect=lambda sn, ctx: {"total_score": 1.0})
    day = MagicMock(side_effect=lambda sn, ctx: {"total_score": 1.0})

    score_universe([{"netuid": 1}], {"weights": {}}, score_hour=hour, score_day=day)
    score_universe([{"netuid": 2}], {"weights": {}}, score_hour=hour, score_day=day)

    assert hour.call_count == 2
