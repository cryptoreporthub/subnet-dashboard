"""Guarded Telegram outcome calibration for council message-intel evidence.

This module is intentionally a one-way adapter: it reads resolved Telegram
receipts and returns plain data.  It never imports council scoring, changes
council weights, or writes to the message-intel database.
"""

from __future__ import annotations

import logging
import math
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

from internal.message_intel.proof import classify_call, stable_author_id
from internal.message_intel.rollup import _conviction_rows, _netuids_from_row, _parse_ts

VERSION = "telegram-outcomes-v1"
DEFAULT_MIN_SAMPLES = 10
DEFAULT_MIN_HIT_RATE = 0.55
DEFAULT_MAX_AGE_DAYS = 30
DEFAULT_CURRENT_WINDOW_HOURS = 72
DEFAULT_MAX_ADJUSTMENT_POINTS = 2.0


def _flag(name: str, default: bool = False) -> bool:
    return os.environ.get(name, "on" if default else "off").strip().lower() in {"1", "true", "yes", "on"}


def _int_env(name: str, default: int, minimum: int = 1) -> int:
    try:
        return max(minimum, int(os.environ.get(name, str(default))))
    except ValueError:
        return default


def _float_env(name: str, default: float, minimum: float = 0.0) -> float:
    try:
        val = float(os.environ.get(name, str(default)))
        if not math.isfinite(val):
            return default
        return max(minimum, val)
    except ValueError:
        return default


def validate_calibration_config() -> List[str]:
    """Validate calibration env vars and log a warning for each bad value.

    Returns a list of human-readable issue strings so callers (and tests) can
    inspect exactly what was wrong.  Values are still clamped to safe ranges
    by the private helpers; this function only surfaces the problems.
    """
    issues: List[str] = []

    # MIN_SAMPLES – must be a positive integer (>= 1)
    raw = os.environ.get("TELEGRAM_EVIDENCE_CALIBRATION_MIN_SAMPLES")
    if raw is not None:
        try:
            val = int(raw)
            if val < 1:
                msg = (
                    f"TELEGRAM_EVIDENCE_CALIBRATION_MIN_SAMPLES={raw!r} is < 1; "
                    f"clamped to 1"
                )
                issues.append(msg)
                logger.warning("calibration config: %s", msg)
        except ValueError:
            msg = (
                f"TELEGRAM_EVIDENCE_CALIBRATION_MIN_SAMPLES={raw!r} is not a valid "
                f"integer; using default {DEFAULT_MIN_SAMPLES}"
            )
            issues.append(msg)
            logger.warning("calibration config: %s", msg)

    # MIN_HIT_RATE – must be a finite float in [0.0, 1.0]
    raw = os.environ.get("TELEGRAM_EVIDENCE_CALIBRATION_MIN_HIT_RATE")
    if raw is not None:
        try:
            val = float(raw)
            if not math.isfinite(val):
                msg = (
                    f"TELEGRAM_EVIDENCE_CALIBRATION_MIN_HIT_RATE={raw!r} is non-finite "
                    f"(nan/inf); using default {DEFAULT_MIN_HIT_RATE}"
                )
                issues.append(msg)
                logger.warning("calibration config: %s", msg)
            elif val > 1.0:
                msg = (
                    f"TELEGRAM_EVIDENCE_CALIBRATION_MIN_HIT_RATE={raw!r} is > 1.0; "
                    f"clamped to 1.0"
                )
                issues.append(msg)
                logger.warning("calibration config: %s", msg)
            elif val < 0.0:
                msg = (
                    f"TELEGRAM_EVIDENCE_CALIBRATION_MIN_HIT_RATE={raw!r} is < 0.0; "
                    f"clamped to 0.0"
                )
                issues.append(msg)
                logger.warning("calibration config: %s", msg)
        except ValueError:
            msg = (
                f"TELEGRAM_EVIDENCE_CALIBRATION_MIN_HIT_RATE={raw!r} is not a valid "
                f"float; using default {DEFAULT_MIN_HIT_RATE}"
            )
            issues.append(msg)
            logger.warning("calibration config: %s", msg)

    # MAX_ADJUSTMENT_POINTS – must be a finite non-negative float; also capped at 5.0
    raw = os.environ.get("TELEGRAM_EVIDENCE_CALIBRATION_MAX_ADJUSTMENT_POINTS")
    if raw is not None:
        try:
            val = float(raw)
            if not math.isfinite(val):
                msg = (
                    f"TELEGRAM_EVIDENCE_CALIBRATION_MAX_ADJUSTMENT_POINTS={raw!r} is non-finite "
                    f"(nan/inf); using default {DEFAULT_MAX_ADJUSTMENT_POINTS}"
                )
                issues.append(msg)
                logger.warning("calibration config: %s", msg)
            elif val < 0.0:
                msg = (
                    f"TELEGRAM_EVIDENCE_CALIBRATION_MAX_ADJUSTMENT_POINTS={raw!r} is < 0; "
                    f"clamped to 0.0"
                )
                issues.append(msg)
                logger.warning("calibration config: %s", msg)
            elif val > 5.0:
                msg = (
                    f"TELEGRAM_EVIDENCE_CALIBRATION_MAX_ADJUSTMENT_POINTS={raw!r} is > 5.0; "
                    f"clamped to 5.0"
                )
                issues.append(msg)
                logger.warning("calibration config: %s", msg)
        except ValueError:
            msg = (
                f"TELEGRAM_EVIDENCE_CALIBRATION_MAX_ADJUSTMENT_POINTS={raw!r} is not a valid "
                f"float; using default {DEFAULT_MAX_ADJUSTMENT_POINTS}"
            )
            issues.append(msg)
            logger.warning("calibration config: %s", msg)

    return issues


# Run startup validation once when the module is first imported so that bad
# environment values are surfaced immediately in the application logs rather
# than silently degrading behaviour at call time.
validate_calibration_config()


def _config() -> Dict[str, Any]:
    return {
        "version": VERSION,
        "enabled": _flag("TELEGRAM_EVIDENCE_CALIBRATION"),
        "min_samples": _int_env("TELEGRAM_EVIDENCE_CALIBRATION_MIN_SAMPLES", DEFAULT_MIN_SAMPLES),
        "min_hit_rate": min(1.0, _float_env("TELEGRAM_EVIDENCE_CALIBRATION_MIN_HIT_RATE", DEFAULT_MIN_HIT_RATE)),
        "max_age_days": _int_env("TELEGRAM_EVIDENCE_CALIBRATION_MAX_AGE_DAYS", DEFAULT_MAX_AGE_DAYS),
        "current_window_hours": _int_env(
            "TELEGRAM_EVIDENCE_CALIBRATION_CURRENT_WINDOW_HOURS", DEFAULT_CURRENT_WINDOW_HOURS
        ),
        "max_adjustment_points": min(
            5.0,
            _float_env(
                "TELEGRAM_EVIDENCE_CALIBRATION_MAX_ADJUSTMENT_POINTS",
                DEFAULT_MAX_ADJUSTMENT_POINTS,
            ),
        ),
    }


def _resolved_receipts(rows: List[Dict[str, Any]], now: datetime) -> List[Dict[str, Any]]:
    receipts: List[Dict[str, Any]] = []
    for row in rows:
        proof = classify_call(row)
        recorded_at = _parse_ts(row.get("price_24h_recorded_at"))
        # A 1h provisional result is deliberately never calibration evidence.
        if not proof["resolved"] or recorded_at is None:
            continue
        receipts.append({**row, "_proof": proof, "_recorded_at": recorded_at})
    return receipts


def calibration_health(*, db=None, now: Optional[datetime] = None) -> Dict[str, Any]:
    """Return reproducible outcome health and all activation/withhold reasons."""
    now = now or datetime.now(timezone.utc)
    cfg = _config()
    rows = _conviction_rows(db)
    receipts = _resolved_receipts(rows, now)
    scored = [r for r in receipts if r["_proof"]["status"] in {"hit", "miss"}]
    fresh_cutoff = now - timedelta(days=cfg["max_age_days"])
    fresh = [r for r in scored if r["_recorded_at"] >= fresh_cutoff]
    hits = sum(r["_proof"]["status"] == "hit" for r in fresh)
    hit_rate = (hits / len(fresh)) if fresh else None
    latest = max((r["_recorded_at"] for r in scored), default=None)
    reasons: List[str] = []
    if not cfg["enabled"]:
        reasons.append("disabled_by_environment")
    if len(fresh) < cfg["min_samples"]:
        reasons.append("insufficient_verified_samples")
    if not fresh:
        reasons.append("no_fresh_verified_outcomes")
    elif hit_rate is not None and hit_rate < cfg["min_hit_rate"]:
        reasons.append("historical_quality_below_threshold")
    if latest is not None and latest < fresh_cutoff:
        reasons.append("verified_outcomes_stale")
    active = not reasons
    quality_edge = max(0.0, (hit_rate or 0.0) - 0.5)
    # Conservative sample maturity avoids a sudden full adjustment at the threshold.
    maturity = min(1.0, len(fresh) / float(cfg["min_samples"] * 2))
    factor = round(1.0 + min(0.10, quality_edge * 0.4) * maturity, 4) if active else 1.0
    return {
        "version": cfg["version"],
        "enabled": cfg["enabled"],
        "active": active,
        "withheld_reasons": reasons,
        "source": "verified_telegram_24h_outcomes",
        "source_sample_size": len(fresh),
        "verified_resolved_count": len(receipts),
        "hits": hits,
        "hit_rate": round(hit_rate, 4) if hit_rate is not None else None,
        "freshness": {
            "max_age_days": cfg["max_age_days"],
            "latest_resolved_at": latest.isoformat() if latest else None,
            "fresh_sample_size": len(fresh),
        },
        "thresholds": {k: cfg[k] for k in ("min_samples", "min_hit_rate", "max_age_days")},
        "factor": factor,
    }


def calibration_for_subnet(netuid: Any, *, db=None, now: Optional[datetime] = None) -> Dict[str, Any]:
    """Return an additive, bounded score adjustment for one subnet's current calls."""
    health = calibration_health(db=db, now=now)
    now = now or datetime.now(timezone.utc)
    cfg = _config()
    try:
        wanted = int(netuid)
    except (TypeError, ValueError):
        return {**health, "applied": False, "adjustment_points": 0.0, "current_evidence": None}
    cutoff = now - timedelta(hours=cfg["current_window_hours"])
    current = []
    for row in _conviction_rows(db):
        proof = classify_call(row)
        timestamp = _parse_ts(row.get("timestamp")) or _parse_ts(row.get("created_at"))
        if not proof["eligible"] or timestamp is None or timestamp < cutoff:
            continue
        if wanted not in _netuids_from_row(row):
            continue
        if proof["direction"] in {"up", "down"}:
            current.append((row, proof, timestamp))
    authors = {stable_author_id(row) for row, _, _ in current}
    direction_sum = sum(1 if proof["direction"] == "up" else -1 for _, proof, _ in current)
    direction = "bullish" if direction_sum > 0 else "bearish" if direction_sum < 0 else "mixed"
    evidence = {
        "netuid": wanted,
        "current_calls": len(current),
        "contributors": len(authors),
        "window_hours": cfg["current_window_hours"],
        "direction": direction,
    }
    reasons = list(health["withheld_reasons"])
    if len(current) < 2 or len(authors) < 2 or direction == "mixed":
        reasons.append("insufficient_current_qualified_consensus")
    applied = health["active"] and not any(r == "insufficient_current_qualified_consensus" for r in reasons)
    sign = 1 if direction == "bullish" else -1
    points = 0.0
    if applied:
        quality_edge = max(0.0, float(health["hit_rate"] or 0.0) - 0.5)
        points = round(sign * min(cfg["max_adjustment_points"], quality_edge * 10.0), 2)
    return {
        **health,
        "active": applied,
        "withheld_reasons": reasons,
        "applied": applied,
        "adjustment_points": points,
        "current_evidence": evidence,
    }