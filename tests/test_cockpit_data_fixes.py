"""APY + council weight normalization checks."""

from internal.council.weights import normalize_council_weights
from internal.subnets.apy import apy_as_percent, subnet_apy_percent


def test_apy_fraction_to_percent():
    assert apy_as_percent(0.247, from_fraction=True) == 24.7


def test_apy_already_percent():
    assert apy_as_percent(2.6) == 2.6


def test_subnet_apy_prefers_staking_fraction():
    sn = {"apy": 5.0, "staking_data": {"apy": 0.18}}
    assert subnet_apy_percent(sn) == 18.0


def test_subnet_apy_none_for_price_proxy_row():
    sn = {"netuid": 1, "apy": 5.2, "price_change_7d": 10.0}
    assert subnet_apy_percent(sn) is None


def test_subnet_apy_registry_top_level_fraction():
    sn = {"id": "sn-12", "apy": 0.25}
    assert subnet_apy_percent(sn) == 25.0


def test_normalize_merges_contrarian_into_dark_horse():
    raw = {"quant": 0.2, "hype": 0.2, "contrarian": 0.5, "dark_horse": 0.3, "technical": 0.1}
    out = normalize_council_weights(raw)
    assert "contrarian" not in out
    assert out["dark_horse"] == 0.5
    assert set(out.keys()) == {"quant", "hype", "dark_horse", "technical"}
