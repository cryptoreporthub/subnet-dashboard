"""Temporary stage timing for daily pick tick profiling (env-gated, default on)."""

from __future__ import annotations

import logging
import os
import statistics
import time
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_active_profile: Optional["TickProfile"] = None


def timing_enabled() -> bool:
    raw = os.environ.get("DAILY_PICK_STAGE_TIMING", "on")
    return str(raw).strip().lower() not in ("0", "false", "no", "off")


class StageTimer:
    """Context manager — ``timer.ms`` set on exit."""

    __slots__ = ("label", "ms", "_t0")

    def __init__(self, label: str) -> None:
        self.label = label
        self.ms = 0.0
        self._t0 = 0.0

    def __enter__(self) -> "StageTimer":
        self._t0 = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.ms = (time.perf_counter() - self._t0) * 1000


class TickProfile:
    """Collect per-tick subnet + I/O counters for one select_daily_pick pass."""

    __slots__ = (
        "conviction_rows_calls",
        "conviction_rows_ms",
        "conviction_rows_cached",
        "subnet_totals",
        "score_stages",
        "io_counts",
        "io_ms",
        "external_attempts",
    )

    def __init__(self) -> None:
        self.conviction_rows_calls = 0
        self.conviction_rows_ms = 0.0
        self.conviction_rows_cached = False
        self.subnet_totals: List[Tuple[Any, float]] = []
        self.score_stages: Dict[str, float] = {}
        self.io_counts: Dict[str, int] = {}
        self.io_ms: Dict[str, float] = {}
        self.external_attempts: Dict[str, int] = {}

    def record_subnet(self, netuid: Any, total_ms: float, stages: Dict[str, float]) -> None:
        self.subnet_totals.append((netuid, total_ms))
        for key, ms in stages.items():
            self.score_stages[key] = self.score_stages.get(key, 0.0) + ms

    def note_io(self, kind: str, ms: float = 0.0) -> None:
        self.io_counts[kind] = self.io_counts.get(kind, 0) + 1
        if ms:
            self.io_ms[kind] = self.io_ms.get(kind, 0.0) + ms

    def note_external(self, kind: str) -> None:
        self.external_attempts[kind] = self.external_attempts.get(kind, 0) + 1

    def subnet_stats(self) -> Dict[str, Any]:
        if not self.subnet_totals:
            return {}
        times = sorted(ms for _, ms in self.subnet_totals)
        median = statistics.median(times)
        outliers = [
            (n, int(ms))
            for n, ms in sorted(self.subnet_totals, key=lambda row: row[1], reverse=True)
            if median > 0 and ms > max(500.0, median * 2.0)
        ][:5]
        top3 = sorted(self.subnet_totals, key=lambda row: row[1], reverse=True)[:3]
        return {
            "count": len(times),
            "min_ms": int(min(times)),
            "max_ms": int(max(times)),
            "median_ms": int(median),
            "p90_ms": int(times[int(len(times) * 0.9) - 1]) if len(times) > 1 else int(times[0]),
            "top3": ",".join(f"sn{n}:{int(ms)}" for n, ms in top3 if n is not None),
            "outliers": ",".join(f"sn{n}:{ms}" for n, ms in outliers) or "none",
            "spread_even": median > 0 and (max(times) / median) < 2.0,
        }


def begin_tick_profile() -> Optional[TickProfile]:
    global _active_profile
    if not timing_enabled():
        return None
    profile = TickProfile()
    _active_profile = profile
    return profile


def end_tick_profile() -> Optional[TickProfile]:
    global _active_profile
    profile = _active_profile
    _active_profile = None
    return profile


def active_profile() -> Optional[TickProfile]:
    return _active_profile


def log_stage_summary(
    prefix: str,
    stages: Dict[str, float],
    *,
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    if not timing_enabled():
        return
    parts = " ".join(f"{k}={int(v)}ms" for k, v in stages.items())
    tail = ""
    if extra:
        tail = " " + " ".join(f"{k}={v}" for k, v in extra.items())
    logger.warning("%s %s%s", prefix, parts, tail)


def log_tick_profile(prefix: str, profile: Optional[TickProfile], *, extra: Optional[Dict[str, Any]] = None) -> None:
    if not timing_enabled() or profile is None:
        return
    stats = profile.subnet_stats()
    score_parts = " ".join(f"{k}={int(v)}ms" for k, v in sorted(profile.score_stages.items()))
    io_parts = " ".join(f"{k}={profile.io_counts[k]}" for k in sorted(profile.io_counts))
    io_ms_parts = " ".join(f"{k}={int(profile.io_ms[k])}ms" for k in sorted(profile.io_ms))
    ext_parts = " ".join(f"{k}={profile.external_attempts[k]}" for k in sorted(profile.external_attempts))
    tail = ""
    if extra:
        tail = " " + " ".join(f"{k}={v}" for k, v in extra.items())
    logger.warning(
        "%s conviction_calls=%s conviction_ms=%s conviction_cached=%s "
        "subnet_min=%s subnet_median=%s subnet_max=%s subnet_p90=%s top3=%s outliers=%s spread_even=%s "
        "score_stages{%s} io_counts{%s} io_ms{%s} external{%s}%s",
        prefix,
        profile.conviction_rows_calls,
        int(profile.conviction_rows_ms),
        profile.conviction_rows_cached,
        stats.get("min_ms", "?"),
        stats.get("median_ms", "?"),
        stats.get("max_ms", "?"),
        stats.get("p90_ms", "?"),
        stats.get("top3", ""),
        stats.get("outliers", "none"),
        stats.get("spread_even", "?"),
        score_parts or "none",
        io_parts or "none",
        io_ms_parts or "none",
        ext_parts or "none",
        tail,
    )
