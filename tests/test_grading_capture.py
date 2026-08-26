"""REV 6 capture bands, schema, and check-order (Part 3 priorities 3–4)."""

from __future__ import annotations

from internal.council.capture import (
    BAND_HIT,
    BAND_MISS,
    BAND_NEAR_HIT,
    BAND_NOISE,
    BAND_UNGRADEABLE,
    REASON_BELOW_C_MIN,
    REASON_BELOW_DEADBAND,
    REASON_PREDICTED_ZERO,
    REASON_WRONG_DIRECTION,
    apply_capture_scale,
    capture_from_row,
    capture_nudge_correct,
    compute_capture,
    legacy_capture_from_correct,
    nudge_multiplier,
)


def test_predicted_zero_is_ungradeable_null_captures():
    result = compute_capture(0.0, 1.5)
    assert result.band == BAND_UNGRADEABLE
    assert result.capture_raw is None
    assert result.capture_capped is None
    assert result.capture_reason == REASON_PREDICTED_ZERO
    assert result.scale == 0.0
    assert nudge_multiplier(result) is None
    assert capture_nudge_correct(result) is None
    assert apply_capture_scale(0.02, result) == 0.0


def test_deadband_exact_half_pct_is_noise_before_c_min():
    # +2% claim, +0.5% actual → c == C_MIN, but deadband fires first.
    result = compute_capture(2.0, 0.5)
    assert result.band == BAND_NOISE
    assert result.capture_reason == REASON_BELOW_DEADBAND
    assert result.capture_raw == 0.25
    assert result.scale == 0.0


def test_deadband_wrong_direction_null_capture():
    # +2% claim landing −0.3% is NOISE, not MISS (noise-first).
    result = compute_capture(2.0, -0.3)
    assert result.band == BAND_NOISE
    assert result.capture_raw is None
    assert result.capture_capped is None
    assert result.capture_reason == REASON_BELOW_DEADBAND
    assert nudge_multiplier(result) is None


def test_deadband_same_sign_keeps_numeric_capture():
    result = compute_capture(2.0, 0.3)
    assert result.band == BAND_NOISE
    assert result.capture_raw == 0.15
    assert result.capture_capped == 0.15
    assert result.capture_reason == REASON_BELOW_DEADBAND


def test_miss_wrong_direction_outside_deadband():
    result = compute_capture(2.0, -1.0)
    assert result.band == BAND_MISS
    assert result.capture_raw is None
    assert result.capture_capped is None
    assert result.capture_reason == REASON_WRONG_DIRECTION
    assert result.scale == -1.0
    assert apply_capture_scale(-0.03, result) == -0.03


def test_hit_at_and_above_one():
    at = compute_capture(2.0, 2.0)
    assert at.band == BAND_HIT
    assert at.capture_raw == 1.0
    assert at.capture_capped == 1.0
    over = compute_capture(2.0, 4.0)
    assert over.band == BAND_HIT
    assert over.capture_raw == 2.0
    assert over.capture_capped == 1.0
    assert nudge_multiplier(over) == 1.0
    assert apply_capture_scale(0.02, over) == 0.02


def test_c_099_is_near_hit_not_hit():
    result = compute_capture(2.0, 1.98)  # c = 0.99
    assert result.band == BAND_NEAR_HIT
    assert abs(result.capture_raw - 0.99) < 1e-9
    assert abs((nudge_multiplier(result) or 0) - 0.99) < 1e-9
    assert abs(apply_capture_scale(0.02, result) - 0.02 * 0.99) < 1e-9


def test_c_min_inclusive_near_hit():
    # |actual| must clear deadband: +3% claim, +0.75% → c == 0.25.
    result = compute_capture(3.0, 0.75)
    assert result.band == BAND_NEAR_HIT
    assert result.capture_raw == 0.25
    assert result.capture_capped == 0.25
    assert apply_capture_scale(0.02, result) == 0.02 * 0.25


def test_below_c_min_is_noise_keeps_numeric():
    result = compute_capture(3.0, 0.6)  # c = 0.2 < 0.25, |actual| > 0.5
    assert result.band == BAND_NOISE
    assert result.capture_reason == REASON_BELOW_C_MIN
    assert abs(result.capture_raw - 0.2) < 1e-9
    assert result.capture_capped is not None
    assert nudge_multiplier(result) is None


def test_negative_direction_symmetry():
    hit = compute_capture(-2.0, -2.0)
    assert hit.band == BAND_HIT
    miss = compute_capture(-2.0, 1.0)
    assert miss.band == BAND_MISS
    assert miss.capture_reason == REASON_WRONG_DIRECTION
    noise = compute_capture(-2.0, 0.3)
    assert noise.band == BAND_NOISE
    assert noise.capture_reason == REASON_BELOW_DEADBAND
    assert noise.capture_raw is None


def test_legacy_row_fallback():
    hit = legacy_capture_from_correct(True)
    assert hit.band == BAND_HIT
    assert hit.capture_capped == 1.0
    miss = legacy_capture_from_correct(False)
    assert miss.band == BAND_MISS
    assert miss.capture_raw is None
    assert miss.capture_reason == "legacy_miss"


def test_capture_from_row_prefers_stored_fields():
    row = {
        "correct": True,
        "predicted_pct": 2.0,
        "actual_pct": -1.0,
        "band": BAND_NOISE,
        "capture_raw": None,
        "capture_capped": None,
        "capture_reason": REASON_BELOW_DEADBAND,
    }
    result = capture_from_row(row)
    assert result.band == BAND_NOISE
    assert result.capture_reason == REASON_BELOW_DEADBAND


def test_capture_from_row_derives_when_fields_missing():
    row = {"correct": True, "predicted_pct": 2.0, "actual_pct": 2.0}
    result = capture_from_row(row)
    assert result.band == BAND_HIT
    assert result.capture_capped == 1.0


def test_pre_phase_a_row_uses_frozen_correct_not_live_math():
    # Live math would be deadband noise; locked replay maps correct=True → HIT.
    row = {"correct": True, "predicted_pct": 2.0, "actual_pct": 0.3}
    result = capture_from_row(row)
    assert result.band == BAND_HIT
    assert result.capture_capped == 1.0


def test_miss_never_emits_negative_ratio():
    result = compute_capture(2.0, -3.0)
    assert result.band == BAND_MISS
    assert result.capture_raw is None
    assert result.capture_capped is None
    dumped = result.as_fields()
    assert dumped["capture_raw"] is None
    assert dumped["capture_capped"] is None
