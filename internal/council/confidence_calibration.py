"""Empirical confidence / red-team calibration from graded predictions.

Derived 2026-07-26 from ``data/predictions.json`` (~60 gradeable resolved,
base hit rate ≈ 0.45) plus daily_picks audit trails.

Key finding: multiplying confidence by raw resolver hit rate (~0.45) collapses
healthy picks below the publish gate. Confidence is a *publishability* score
informed by model strength; hit rate only nudges, never replaces the prior.
"""

from __future__ import annotations

# Center for a complete, agreed healthy pick (before score boost / audit).
# Must clear DAILY_PICK_PUBLISH_GATE=0.40 after mild red-team haircuts.
COLD_START_PRIOR = 0.58

# Blend weights when enough graded outcomes exist (min_n in state_vector).
# prior = PRIOR_BLEND_COLD * COLD_START + PRIOR_BLEND_HIT * clamp(hit_rate)
# At hit=0.45 → prior ≈ 0.55 — still publishable; never collapses to coin-flip.
PRIOR_BLEND_COLD = 0.70
PRIOR_BLEND_HIT = 0.30
HIT_RATE_FLOOR = 0.40
HIT_RATE_CEIL = 0.65

# Soft reliability nudge after strength formula (not a prior replacement).
# factor = RELIABILITY_BASE + RELIABILITY_SLOPE * hit_rate
# hit=0.45 → ≈0.985; hit=0.55 → ≈1.01
RELIABILITY_BASE = 0.88
RELIABILITY_SLOPE = 0.24

# Map total_score (0-100) into a publishability boost added after the product.
# Scores 60→0, 80→+0.06, 100→+0.12. HOLD days often score 85+ with low conf.
SCORE_BOOST_FLOOR = 60.0
SCORE_BOOST_CEIL = 100.0
SCORE_BOOST_MAX = 0.12


def blended_prior(hit_rate: float | None) -> float:
    """Publishable prior — never collapses to raw coin-flip hit rate."""
    if hit_rate is None:
        return COLD_START_PRIOR
    clamped = max(HIT_RATE_FLOOR, min(HIT_RATE_CEIL, float(hit_rate)))
    return PRIOR_BLEND_COLD * COLD_START_PRIOR + PRIOR_BLEND_HIT * clamped


def reliability_factor(hit_rate: float | None) -> float:
    if hit_rate is None:
        return 1.0
    return RELIABILITY_BASE + RELIABILITY_SLOPE * float(hit_rate)


def score_boost(total_score: float | None) -> float:
    if total_score is None:
        return 0.0
    try:
        ts = float(total_score)
    except (TypeError, ValueError):
        return 0.0
    span = SCORE_BOOST_CEIL - SCORE_BOOST_FLOOR
    if span <= 0:
        return 0.0
    frac = max(0.0, min(1.0, (ts - SCORE_BOOST_FLOOR) / span))
    return SCORE_BOOST_MAX * frac
