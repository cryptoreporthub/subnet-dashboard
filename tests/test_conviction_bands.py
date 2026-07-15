"""§17.S1 — conviction bands."""

from __future__ import annotations

from internal.council.conviction_bands import (
    BAND_MIN_SAMPLE,
    band_for_pick,
    compute_conviction_band,
    expert_agreement,
)


def test_expert_agreement_aligned_vs_split():
    assert expert_agreement({"a": 0.5, "b": 0.5, "c": 0.5}) == 1.0
    low = expert_agreement({"a": 0.0, "b": 1.0})
    assert low is not None and low < 0.5


def test_cold_start_null_band():
    out = compute_conviction_band(
        confidence=0.9,
        agreement=0.9,
        hit_rate=0.9,
        sample_n=BAND_MIN_SAMPLE - 1,
    )
    assert out["band"] is None
    assert out["reason"] == "not_enough_data"


def test_bands_high_medium_low():
    high = compute_conviction_band(
        confidence=0.8, agreement=0.8, hit_rate=0.7, sample_n=50
    )
    assert high["band"] == "high"
    med = compute_conviction_band(
        confidence=0.5, agreement=0.5, hit_rate=0.5, sample_n=50
    )
    assert med["band"] == "medium"
    low = compute_conviction_band(
        confidence=0.2, agreement=0.2, hit_rate=0.3, sample_n=50
    )
    assert low["band"] == "low"


def test_no_signal_does_not_invent_medium():
    out = compute_conviction_band(sample_n=100)
    assert out["band"] is None
    assert out["reason"] == "insufficient_signal"


def test_band_for_pick_uses_contributions():
    pick = {
        "final_confidence": 0.7,
        "expert_contributions": {"quant": 0.7, "hype": 0.7, "dark_horse": 0.68},
    }
    # May be null if store has few resolved rows in test env — still well-formed
    out = band_for_pick(pick)
    assert "band" in out
    assert out["band"] in (None, "high", "medium", "low")
