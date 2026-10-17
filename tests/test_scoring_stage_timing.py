"""Stage timings explain where per-subnet scoring time goes (snapshot coverage.timing)."""

import time

from internal.council import score_snapshots as snaps
from internal.council.stage_timing import collect_stage_seconds, timed_stage
from internal.council.state_vector import score_subnet_for_day

SUBNET = {
    "netuid": 97, "name": "Ingot", "price": 0.013, "emission": 0.5, "volume": 4000.0,
    "price_change_24h": 4.5, "price_change_7d": -12.0, "price_change_30d": -35.0,
}


@timed_stage("probe")
def _probe(delay: float) -> str:
    time.sleep(delay)
    return "ok"


def test_collector_accumulates_only_inside_context_and_nests():
    assert _probe(0.0) == "ok"  # no collector: plain call
    with collect_stage_seconds() as outer:
        _probe(0.01)
        with collect_stage_seconds() as inner:
            _probe(0.01)
        _probe(0.01)
    assert inner["probe"] >= 0.009
    assert outer["probe"] >= 0.019 and outer["probe"] < 0.2 + inner["probe"] + 0.1


def test_day_scoring_reports_its_main_stages():
    with collect_stage_seconds() as stages:
        score_subnet_for_day(dict(SUBNET), {})
    for name in ("indicators", "price_history", "signal_impact", "experts", "confidence", "recovery_context"):
        assert name in stages, name


def test_build_snapshot_exposes_stage_seconds(monkeypatch):
    monkeypatch.setattr("internal.pump.state.load_state", lambda path=None: {"subnets": {}})
    out = snaps.build_full_universe_snapshot([dict(SUBNET)], {}, score_hour=False)
    timing = out["build_stage_timing"]
    assert timing["day_stage_seconds"], "no stage breakdown reported"
    assert "indicators" in timing["day_stage_seconds"]
    assert timing["day_unattributed_seconds"] >= 0.0
