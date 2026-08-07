from datetime import datetime, timedelta, timezone


def _row(i, *, direction="up", outcome="pump", age_days=1, netuid=7, author=None):
    now = datetime.now(timezone.utc)
    return {
        "id": i, "source": "telegram", "author_id": author or f"a{i}",
        "timestamp": (now - timedelta(hours=i)).isoformat(), "created_at": now.isoformat(),
        "verdict": "bullish" if direction == "up" else "bearish",
        "predicted_direction": direction, "conviction": 70, "tao_usd_price": 1.0,
        "snap_netuid": netuid, "netuid": netuid, "outcome": outcome,
        "pump_pct_max": 6.0 if outcome == "pump" else None, "price_24h": 1.06,
        "price_24h_recorded_at": (now - timedelta(days=age_days)).isoformat(),
    }


def test_calibration_withholds_sparse_and_disabled_data(monkeypatch):
    from internal.message_intel import calibration

    monkeypatch.setattr(calibration, "_conviction_rows", lambda db=None: [_row(1)])
    health = calibration.calibration_health()
    assert health["active"] is False
    assert "disabled_by_environment" in health["withheld_reasons"]
    assert "insufficient_verified_samples" in health["withheld_reasons"]
    assert health["factor"] == 1.0


def test_calibration_applies_bounded_explainable_adjustment(monkeypatch):
    from internal.message_intel import calibration

    monkeypatch.setenv("TELEGRAM_EVIDENCE_CALIBRATION", "on")
    monkeypatch.setenv("TELEGRAM_EVIDENCE_CALIBRATION_MIN_SAMPLES", "4")
    monkeypatch.setenv("TELEGRAM_EVIDENCE_CALIBRATION_MAX_ADJUSTMENT_POINTS", "1.5")
    rows = [_row(i, author=f"a{i}") for i in range(1, 7)]
    monkeypatch.setattr(calibration, "_conviction_rows", lambda db=None: rows)
    result = calibration.calibration_for_subnet(7)
    assert result["active"] is True
    assert result["applied"] is True
    assert 0 < result["adjustment_points"] <= 1.5
    assert result["current_evidence"]["contributors"] >= 2


def test_calibration_withholds_poor_or_stale_history(monkeypatch):
    from internal.message_intel import calibration

    monkeypatch.setenv("TELEGRAM_EVIDENCE_CALIBRATION", "on")
    monkeypatch.setenv("TELEGRAM_EVIDENCE_CALIBRATION_MIN_SAMPLES", "3")
    poor = [_row(i, outcome="dump", author=f"a{i}") for i in range(1, 4)]
    monkeypatch.setattr(calibration, "_conviction_rows", lambda db=None: poor)
    assert "historical_quality_below_threshold" in calibration.calibration_health()["withheld_reasons"]
    stale = [_row(i, age_days=60, author=f"a{i}") for i in range(1, 4)]
    monkeypatch.setattr(calibration, "_conviction_rows", lambda db=None: stale)
    assert "no_fresh_verified_outcomes" in calibration.calibration_health()["withheld_reasons"]


def test_validate_calibration_config_accepts_valid_values(monkeypatch):
    """No issues returned when all three env vars are within valid ranges."""
    from internal.message_intel import calibration

    monkeypatch.setenv("TELEGRAM_EVIDENCE_CALIBRATION_MIN_SAMPLES", "10")
    monkeypatch.setenv("TELEGRAM_EVIDENCE_CALIBRATION_MIN_HIT_RATE", "0.55")
    monkeypatch.setenv("TELEGRAM_EVIDENCE_CALIBRATION_MAX_ADJUSTMENT_POINTS", "2.0")
    issues = calibration.validate_calibration_config()
    assert issues == []


def test_validate_calibration_config_min_samples_below_one(monkeypatch):
    """MIN_SAMPLES < 1 produces a warning and is reported as an issue."""
    from internal.message_intel import calibration

    monkeypatch.setenv("TELEGRAM_EVIDENCE_CALIBRATION_MIN_SAMPLES", "0")
    issues = calibration.validate_calibration_config()
    assert len(issues) == 1
    assert "MIN_SAMPLES" in issues[0]
    assert "clamped" in issues[0]


def test_validate_calibration_config_min_samples_not_integer(monkeypatch):
    """Non-integer MIN_SAMPLES produces a warning mentioning the default."""
    from internal.message_intel import calibration

    monkeypatch.setenv("TELEGRAM_EVIDENCE_CALIBRATION_MIN_SAMPLES", "abc")
    issues = calibration.validate_calibration_config()
    assert len(issues) == 1
    assert "MIN_SAMPLES" in issues[0]
    assert "not a valid integer" in issues[0]


def test_validate_calibration_config_min_hit_rate_above_one(monkeypatch):
    """MIN_HIT_RATE > 1.0 is flagged and clamped."""
    from internal.message_intel import calibration

    monkeypatch.setenv("TELEGRAM_EVIDENCE_CALIBRATION_MIN_HIT_RATE", "1.5")
    issues = calibration.validate_calibration_config()
    assert len(issues) == 1
    assert "MIN_HIT_RATE" in issues[0]
    assert "clamped" in issues[0]
    # The running config must cap it at 1.0
    cfg = calibration._config()
    assert cfg["min_hit_rate"] <= 1.0


def test_validate_calibration_config_min_hit_rate_negative(monkeypatch):
    """MIN_HIT_RATE < 0.0 is flagged and clamped to 0.0."""
    from internal.message_intel import calibration

    monkeypatch.setenv("TELEGRAM_EVIDENCE_CALIBRATION_MIN_HIT_RATE", "-0.1")
    issues = calibration.validate_calibration_config()
    assert len(issues) == 1
    assert "MIN_HIT_RATE" in issues[0]
    assert "clamped" in issues[0]


def test_validate_calibration_config_min_hit_rate_not_float(monkeypatch):
    """Non-float MIN_HIT_RATE produces a warning mentioning the default."""
    from internal.message_intel import calibration

    monkeypatch.setenv("TELEGRAM_EVIDENCE_CALIBRATION_MIN_HIT_RATE", "not_a_number")
    issues = calibration.validate_calibration_config()
    assert len(issues) == 1
    assert "MIN_HIT_RATE" in issues[0]
    assert "not a valid float" in issues[0]


def test_validate_calibration_config_max_adjustment_negative(monkeypatch):
    """MAX_ADJUSTMENT_POINTS < 0 is flagged; _config clamps it to 0."""
    from internal.message_intel import calibration

    monkeypatch.setenv("TELEGRAM_EVIDENCE_CALIBRATION_MAX_ADJUSTMENT_POINTS", "-3.0")
    issues = calibration.validate_calibration_config()
    assert len(issues) == 1
    assert "MAX_ADJUSTMENT_POINTS" in issues[0]
    assert "clamped" in issues[0]
    cfg = calibration._config()
    assert cfg["max_adjustment_points"] >= 0.0


def test_validate_calibration_config_max_adjustment_above_cap(monkeypatch):
    """MAX_ADJUSTMENT_POINTS > 5.0 is flagged and clamped to 5.0."""
    from internal.message_intel import calibration

    monkeypatch.setenv("TELEGRAM_EVIDENCE_CALIBRATION_MAX_ADJUSTMENT_POINTS", "99.0")
    issues = calibration.validate_calibration_config()
    assert len(issues) == 1
    assert "MAX_ADJUSTMENT_POINTS" in issues[0]
    assert "clamped" in issues[0]
    cfg = calibration._config()
    assert cfg["max_adjustment_points"] <= 5.0


def test_validate_calibration_config_max_adjustment_not_float(monkeypatch):
    """Non-float MAX_ADJUSTMENT_POINTS produces a warning mentioning the default."""
    from internal.message_intel import calibration

    monkeypatch.setenv("TELEGRAM_EVIDENCE_CALIBRATION_MAX_ADJUSTMENT_POINTS", "???")
    issues = calibration.validate_calibration_config()
    assert len(issues) == 1
    assert "MAX_ADJUSTMENT_POINTS" in issues[0]
    assert "not a valid float" in issues[0]


def test_validate_calibration_config_multiple_bad_values(monkeypatch):
    """All three bad values are reported together in a single call."""
    from internal.message_intel import calibration

    monkeypatch.setenv("TELEGRAM_EVIDENCE_CALIBRATION_MIN_SAMPLES", "-5")
    monkeypatch.setenv("TELEGRAM_EVIDENCE_CALIBRATION_MIN_HIT_RATE", "2.0")
    monkeypatch.setenv("TELEGRAM_EVIDENCE_CALIBRATION_MAX_ADJUSTMENT_POINTS", "-1.0")
    issues = calibration.validate_calibration_config()
    assert len(issues) == 3
    keys = " ".join(issues)
    assert "MIN_SAMPLES" in keys
    assert "MIN_HIT_RATE" in keys
    assert "MAX_ADJUSTMENT_POINTS" in keys


def test_validate_calibration_config_warnings_are_logged(monkeypatch, caplog):
    """Out-of-range values emit logger.warning entries."""
    import logging
    from internal.message_intel import calibration

    monkeypatch.setenv("TELEGRAM_EVIDENCE_CALIBRATION_MIN_HIT_RATE", "9.9")
    with caplog.at_level(logging.WARNING, logger="internal.message_intel.calibration"):
        issues = calibration.validate_calibration_config()
    assert issues
    assert any("MIN_HIT_RATE" in r.message for r in caplog.records)


def test_validate_calibration_config_nan_hit_rate(monkeypatch):
    """NaN is non-finite and must be reported as an issue for MIN_HIT_RATE."""
    from internal.message_intel import calibration

    monkeypatch.setenv("TELEGRAM_EVIDENCE_CALIBRATION_MIN_HIT_RATE", "nan")
    issues = calibration.validate_calibration_config()
    assert len(issues) == 1
    assert "MIN_HIT_RATE" in issues[0]
    assert "non-finite" in issues[0]


def test_validate_calibration_config_inf_hit_rate(monkeypatch):
    """Infinity is non-finite and must be reported as an issue for MIN_HIT_RATE."""
    from internal.message_intel import calibration

    monkeypatch.setenv("TELEGRAM_EVIDENCE_CALIBRATION_MIN_HIT_RATE", "inf")
    issues = calibration.validate_calibration_config()
    assert len(issues) == 1
    assert "MIN_HIT_RATE" in issues[0]
    assert "non-finite" in issues[0]


def test_validate_calibration_config_nan_max_adjustment(monkeypatch):
    """NaN is non-finite and must be reported as an issue for MAX_ADJUSTMENT_POINTS."""
    from internal.message_intel import calibration

    monkeypatch.setenv("TELEGRAM_EVIDENCE_CALIBRATION_MAX_ADJUSTMENT_POINTS", "nan")
    issues = calibration.validate_calibration_config()
    assert len(issues) == 1
    assert "MAX_ADJUSTMENT_POINTS" in issues[0]
    assert "non-finite" in issues[0]


def test_validate_calibration_config_inf_max_adjustment(monkeypatch):
    """Negative infinity must be reported as an issue for MAX_ADJUSTMENT_POINTS."""
    from internal.message_intel import calibration

    monkeypatch.setenv("TELEGRAM_EVIDENCE_CALIBRATION_MAX_ADJUSTMENT_POINTS", "-inf")
    issues = calibration.validate_calibration_config()
    assert len(issues) == 1
    assert "MAX_ADJUSTMENT_POINTS" in issues[0]
    assert "non-finite" in issues[0]


def test_config_returns_default_for_nan_hit_rate(monkeypatch):
    """_config() must fall back to DEFAULT_MIN_HIT_RATE when the env var is nan."""
    from internal.message_intel import calibration

    monkeypatch.setenv("TELEGRAM_EVIDENCE_CALIBRATION_MIN_HIT_RATE", "nan")
    cfg = calibration._config()
    assert cfg["min_hit_rate"] == calibration.DEFAULT_MIN_HIT_RATE


def test_config_returns_default_for_inf_hit_rate(monkeypatch):
    """_config() must fall back to DEFAULT_MIN_HIT_RATE when the env var is inf."""
    from internal.message_intel import calibration

    monkeypatch.setenv("TELEGRAM_EVIDENCE_CALIBRATION_MIN_HIT_RATE", "inf")
    cfg = calibration._config()
    assert cfg["min_hit_rate"] == calibration.DEFAULT_MIN_HIT_RATE


def test_config_returns_default_for_nan_max_adjustment(monkeypatch):
    """_config() must fall back to DEFAULT_MAX_ADJUSTMENT_POINTS when the env var is nan."""
    from internal.message_intel import calibration

    monkeypatch.setenv("TELEGRAM_EVIDENCE_CALIBRATION_MAX_ADJUSTMENT_POINTS", "nan")
    cfg = calibration._config()
    assert cfg["max_adjustment_points"] == calibration.DEFAULT_MAX_ADJUSTMENT_POINTS


def test_config_returns_default_for_neg_inf_max_adjustment(monkeypatch):
    """_config() must fall back to DEFAULT_MAX_ADJUSTMENT_POINTS when the env var is -inf."""
    from internal.message_intel import calibration

    monkeypatch.setenv("TELEGRAM_EVIDENCE_CALIBRATION_MAX_ADJUSTMENT_POINTS", "-inf")
    cfg = calibration._config()
    assert cfg["max_adjustment_points"] == calibration.DEFAULT_MAX_ADJUSTMENT_POINTS


def test_council_score_is_unchanged_when_calibration_unavailable(monkeypatch):
    from internal.council import state_vector

    monkeypatch.setattr(
        "internal.message_intel.calibration.calibration_for_subnet",
        lambda *args, **kwargs: {"adjustment_points": 0.0, "active": False, "applied": False},
    )
    sn = {"netuid": 7, "name": "Seven", "price": 1.0, "emission": 1.0, "apy": 10.0}
    result = state_vector.score_subnet_for_day(sn, {"skip_pump_overlay": True})
    assert result["telegram_evidence_calibration"]["adjustment_points"] == 0.0