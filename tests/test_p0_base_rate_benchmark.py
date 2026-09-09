"""P0.2 — Wilson CI, unconditional aggregation, comparison labels."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from internal.learning.base_rate import (
    COUNCIL_LABEL,
    UNFREEZE_BAR_TEXT,
    UNFREEZE_MIN_N,
    aggregate_base_rates,
    comparison_table,
    iter_unconditional_observations,
    observation_hit_within_1h,
    wilson_binomial_ci,
)


def test_wilson_interval_hand_computed_n100_p50():
    # Hand check: n=100, hits=50, z=1.96
    ci = wilson_binomial_ci(50, 100)
    assert ci["low"] == pytest.approx(0.4038, abs=5e-4)
    assert ci["high"] == pytest.approx(0.5962, abs=5e-4)


def test_wilson_interval_extremes_and_empty():
    assert wilson_binomial_ci(0, 0) == {"low": None, "high": None, "centre": None}
    ci0 = wilson_binomial_ci(0, 20)
    assert ci0["low"] == 0.0
    assert ci0["high"] is not None and ci0["high"] > 0
    ci1 = wilson_binomial_ci(20, 20)
    assert ci1["high"] == 1.0
    assert ci1["low"] is not None and ci1["low"] < 1.0
    with pytest.raises(ValueError):
        wilson_binomial_ci(5, 3)


def test_observation_hit_and_iter_synthetic_series():
    ref = 100.0
    assert observation_hit_within_1h(
        ref, [{"high": 101.0, "close": 100.5}], claim_pct=2.0
    ) is False
    assert observation_hit_within_1h(
        ref, [{"high": 102.0, "close": 101.0}], claim_pct=2.0
    ) is True

    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    candles = []
    # 5 hourly candles: closes 100,100,100,103,100 — obs0 window has high 100 only → miss
    # Craft: candle0 close 100; candle1 high 103 → hit
    prices = [
        (0, 100.0, 100.0),
        (1, 103.0, 101.0),  # high +3% within 1h of prior
        (2, 100.5, 100.0),
        (3, 100.0, 99.0),
    ]
    for hour, high, close in prices:
        candles.append(
            {
                "timestamp": (start + timedelta(hours=hour)).isoformat().replace("+00:00", "Z"),
                "high": high,
                "close": close,
            }
        )
    obs = iter_unconditional_observations(candles, claim_pct=2.0)
    assert len(obs) == 3  # last candle has no forward window
    assert obs[0]["hit"] is True
    assert obs[1]["hit"] is False
    assert obs[2]["hit"] is False


def test_aggregate_per_class_bucketing():
    by_class = {
        "CHOP": [{"hit": True}, {"hit": False}, {"hit": False}],
        "PUMP_ONLY": [{"hit": True}, {"hit": True}],
    }
    out = aggregate_base_rates(by_class)
    assert out["by_class"]["CHOP"]["n"] == 3
    assert out["by_class"]["CHOP"]["hits"] == 1
    assert out["by_class"]["CHOP"]["hit_rate"] == pytest.approx(0.3333)
    assert out["by_class"]["PUMP_ONLY"]["hit_rate"] == 1.0
    assert out["overall"]["n"] == 5
    assert out["overall"]["hits"] == 3
    assert out["unfreeze_significance_bar"]["min_n"] == UNFREEZE_MIN_N
    assert "Wilson lower bound" in out["unfreeze_significance_bar"]["text"]


def test_comparison_labels_council_unaudited_and_mfe_unavailable():
    base = {
        "overall": {
            "n": 10,
            "hits": 2,
            "hit_rate": 0.2,
            "wilson_95": wilson_binomial_ci(2, 10),
        }
    }
    rows = comparison_table(base, mfe_hit_rates=None)
    names = [r["name"] for r in rows]
    assert COUNCIL_LABEL in names
    council = next(r for r in rows if r["name"] == COUNCIL_LABEL)
    assert council["rate_pct"] == 50.5
    assert "UNAUDITED" in council["audit_status"]
    early_mfe = next(r for r in rows if r["name"] == "Early Pump (MFE-regraded)")
    assert early_mfe["rate_pct"] is None
    assert "unavailable" in early_mfe["audit_status"]
    assert "UNFREEZE" in UNFREEZE_BAR_TEXT.upper() or "Wilson" in UNFREEZE_BAR_TEXT
