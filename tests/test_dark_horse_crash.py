"""Dark Horse crash-tail feature tests."""

from internal.council.dark_horse_crash import (
    FORMULA_VERSION,
    crash_tail_features,
    dark_horse_crash_score,
)


def test_crash_tail_features_drawdown_stress():
    sn = {
        "price_change_24h": -8.0,
        "price_change_7d": -12.0,
        "price_change_30d": -10.0,
    }
    feats = crash_tail_features(sn)
    assert feats["crash_stress"] > 0.4
    assert feats["drawdown_pct"] == -12.0
    assert 0.0 <= feats["crash_opportunity"] <= 1.0


def test_recovery_boosts_opportunity():
    stressed = {"price_change_24h": 2.0, "price_change_7d": -10.0, "price_change_30d": -8.0}
    flat = {"price_change_24h": -10.0, "price_change_7d": -10.0, "price_change_30d": -10.0}
    assert dark_horse_crash_score(stressed) >= dark_horse_crash_score(flat)


def test_formula_version_semver():
    assert FORMULA_VERSION.startswith("1.")
