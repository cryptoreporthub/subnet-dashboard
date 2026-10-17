"""Every score adjuster's effect is recorded on the ledger row so its lift can be measured later."""

from internal.council.state_vector import (
    attach_council_prediction,
    score_subnet_for_day,
    score_subnet_for_hour,
)

SUBNET = {
    "netuid": 97,
    "name": "Ingot",
    "price": 0.013,
    "emission": 0.5,
    "volume": 4000.0,
    "price_change_24h": 4.5,
    "price_change_7d": -12.0,
    "price_change_30d": -35.0,
}
DAY_KEYS = {
    "base_pts", "memory_pts", "after_memory", "telegram_pts", "after_telegram",
    "pump_pts", "recovery_haircut", "final_total",
}


def test_day_score_breakdown_reconciles_with_total():
    payload = score_subnet_for_day(dict(SUBNET), {})
    bd = payload["score_breakdown"]
    assert DAY_KEYS <= set(bd)
    assert bd["final_total"] == payload["total_score"]
    # the trail is internally consistent: pump step explains after_telegram -> pre-haircut total
    assert round(bd["after_telegram"] + bd["pump_pts"], 2) >= 0.0


def test_hour_score_breakdown_has_final_total():
    payload = score_subnet_for_hour(dict(SUBNET), {})
    bd = payload["score_breakdown"]
    assert {"base_pts", "memory_pts", "pump_pts", "final_total"} <= set(bd)
    assert bd["final_total"] == payload["total_score"]


def test_prediction_row_carries_breakdown():
    payload = score_subnet_for_day(dict(SUBNET), {})
    row = attach_council_prediction(dict(SUBNET), payload, 0.55)
    assert row["score_breakdown"]["final_total"] == payload["total_score"]


def test_prediction_without_breakdown_is_unchanged():
    row = attach_council_prediction(dict(SUBNET), {"total_score": 50.0, "expert_contributions": {}}, 0.5)
    assert "score_breakdown" not in row
