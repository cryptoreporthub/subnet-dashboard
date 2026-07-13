"""DEEP VALUE / undervalued verdict — yield vs 24h price change."""

from internal.council.state_vector import score_subnet_for_day
from internal.subnets.apy import undervalued_score, undervalued_verdict


def test_undervalued_high_apy_lagging_price():
  sn = {"netuid": 1, "apy": 25.0, "price_change_24h": -8.0, "emission": 2.0, "volume": 1_000_000}
  assert undervalued_score(sn) == 33.0
  assert undervalued_verdict(sn) == "deep_value"


def test_not_undervalued_when_price_already_pumped():
  sn = {"netuid": 2, "apy": 25.0, "price_change_24h": 22.0, "emission": 2.0, "volume": 1_000_000}
  assert undervalued_score(sn) == 3.0
  assert undervalued_verdict(sn) == "fair"


def test_day_score_favors_lagging_price_over_pumped_peer():
  lagging = {
    "netuid": 10,
    "name": "Lag",
    "apy": 30.0,
    "price_change_24h": -10.0,
    "emission": 2.0,
    "volume": 500_000,
    "price": 1.0,
  }
  pumped = {
    "netuid": 11,
    "name": "Pump",
    "apy": 30.0,
    "price_change_24h": 25.0,
    "emission": 2.0,
    "volume": 500_000,
    "price": 1.0,
  }
  ctx = {"tao_change_24h": 0.0, "weights": {"quant": 1.0, "hype": 1.0, "dark_horse": 1.0, "technical": 1.0}}
  lag = score_subnet_for_day(lagging, ctx)
  pump = score_subnet_for_day(pumped, ctx)
  assert lag["scenario_tags"]["valuation"] == "deep_value"
  assert pump["scenario_tags"]["valuation"] == "fair"
