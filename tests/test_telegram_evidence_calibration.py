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


def test_council_score_is_unchanged_when_calibration_unavailable(monkeypatch):
    from internal.council import state_vector

    monkeypatch.setattr(
        "internal.message_intel.calibration.calibration_for_subnet",
        lambda *args, **kwargs: {"adjustment_points": 0.0, "active": False, "applied": False},
    )
    sn = {"netuid": 7, "name": "Seven", "price": 1.0, "emission": 1.0, "apy": 10.0}
    result = state_vector.score_subnet_for_day(sn, {"skip_pump_overlay": True})
    assert result["telegram_evidence_calibration"]["adjustment_points"] == 0.0