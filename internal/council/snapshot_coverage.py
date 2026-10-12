"""Phase 1 score-snapshot coverage telemetry (honesty only — no cap policy change)."""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

from internal.subnets.tradable import subnet_netuid


def env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or str(raw).strip() == "":
        return default
    return int(raw)


PHASE1_CONSECUTIVE_PARTIAL_CYCLES = max(
    1,
    env_int("PHASE1_CONSECUTIVE_PARTIAL_CYCLES", 3),
)
PHASE1_COVERAGE_CAPTURE_MAX_SECONDS = max(
    1,
    env_int("PHASE1_COVERAGE_CAPTURE_MAX_SECONDS", 600),
)
MEMBERSHIP_FRESH_MAX_SECONDS = max(
    60,
    env_int("PHASE1_MEMBERSHIP_FRESH_MAX_SECONDS", 172800),
)

_last_cycle: Dict[str, Any] = {}
_consecutive_partial_cycles = 0


def _parse_iso(value: Any) -> Optional[datetime]:
    if not value or not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def membership_fresh(
    resolved_at: Optional[str],
    *,
    max_age_seconds: Optional[int] = None,
    now: Optional[datetime] = None,
) -> bool:
    """Freshness seam — wall clock today; block lag when chain sourcing lands."""
    parsed = _parse_iso(resolved_at)
    if parsed is None:
        return False
    limit = max_age_seconds if max_age_seconds is not None else MEMBERSHIP_FRESH_MAX_SECONDS
    clock = now or datetime.now(timezone.utc)
    age = (clock - parsed).total_seconds()
    return age >= 0 and age <= limit


def load_membership_receipt() -> Dict[str, Any]:
    try:
        from internal.subnet_universe import get_snapshot, universe_snapshot_feed_meta

        snap = get_snapshot()
        feed = universe_snapshot_feed_meta(snap)
        netuids = tuple(int(n) for n in snap.netuids if int(n) > 0)
        return {
            "source": feed.get("source"),
            "sources": list(feed.get("sources") or []),
            "resolved_at": snap.resolved_at,
            "universe_status": snap.status,
            "degraded": bool(snap.degraded),
            "cap_reached": bool(snap.cap_reached),
            "refresh_incomplete": bool(snap.refresh_incomplete),
            "expected_netuids": list(netuids),
            "fresh": membership_fresh(snap.resolved_at),
            "root_netuid_in_membership": 0 in snap.netuids,
            "message": snap.message,
        }
    except Exception as exc:
        return {
            "source": "unknown",
            "sources": [],
            "resolved_at": None,
            "universe_status": "unknown",
            "degraded": True,
            "cap_reached": False,
            "refresh_incomplete": True,
            "expected_netuids": [],
            "fresh": False,
            "root_netuid_in_membership": False,
            "message": str(exc),
        }


def membership_scoring_expected(membership_netuids: List[int]) -> List[int]:
    """Pinned membership denominator before scoring — never tradable∩shrink."""
    return sorted({int(n) for n in membership_netuids if int(n) > 0})


def tradable_netuid_set(tradable_rows: List[Dict[str, Any]]) -> Set[int]:
    return {
        n
        for n in (subnet_netuid(row) for row in tradable_rows)
        if n is not None and int(n) > 0
    }


def scoring_expected_netuids(
    membership_netuids: List[int],
    tradable_rows: List[Dict[str, Any]],
) -> List[int]:
    """Backward-compatible alias — denominator is full membership only."""
    return membership_scoring_expected(membership_netuids)


def _horizon_block(
    *,
    horizon: str,
    expected: List[int],
    succeeded: List[int],
    failed: List[Dict[str, Any]],
    hour_copied_from_day: bool,
    tradable_netuids: Optional[Set[int]] = None,
    attempted_netuids: Optional[List[int]] = None,
) -> Dict[str, Any]:
    expected_set = set(expected)
    succeeded_set = set(succeeded)
    failed_ids = {
        int(f["netuid"])
        for f in failed
        if isinstance(f, dict) and f.get("netuid") is not None
    }
    if attempted_netuids is not None:
        attempted_set = {int(n) for n in attempted_netuids}
    else:
        attempted_set = succeeded_set | failed_ids
    if tradable_netuids is None:
        missing_not_admitted = []
    else:
        tradable_set = set(tradable_netuids)
        missing_not_admitted = sorted(expected_set - tradable_set)
    unaccounted = sorted(expected_set - succeeded_set - failed_ids)
    scored_complete = (
        succeeded_set == expected_set
        and bool(expected_set)
        and not missing_not_admitted
        and not unaccounted
    )
    hour_status: Optional[str] = None
    if horizon == "hour":
        if hour_copied_from_day:
            hour_status = "copied"
            # Copied hour rows satisfy the horizon without independent hour scoring attempts.
            complete = scored_complete
        else:
            hour_status = "scored"
            complete = scored_complete and bool(attempted_set)
    else:
        complete = scored_complete
    return {
        "horizon": horizon,
        "expected": expected,
        "attempted": len(attempted_set),
        "attempted_netuids": sorted(attempted_set),
        "succeeded": sorted(succeeded_set),
        "failed": failed,
        "missing_not_admitted": missing_not_admitted,
        "unaccounted": unaccounted,
        "skipped_invalid": max(0, len(expected) - len(succeeded_set) - len(failed)),
        "complete": complete,
        "status": hour_status,
        "hour_copied_from_day": hour_copied_from_day if horizon == "hour" else False,
    }


def membership_allows_complete(receipt: Dict[str, Any]) -> bool:
    if not receipt.get("fresh"):
        return False
    status = str(receipt.get("universe_status") or "")
    if status in ("unknown", "emergency_registry"):
        return False
    if receipt.get("degraded"):
        return False
    if receipt.get("cap_reached"):
        return False
    if receipt.get("refresh_incomplete"):
        return False
    return True


def build_coverage_block(
    *,
    receipt: Dict[str, Any],
    day_expected: List[int],
    day_succeeded: List[int],
    day_failed: List[Dict[str, Any]],
    hour_succeeded: List[int],
    hour_failed: List[Dict[str, Any]],
    day_attempted: Optional[List[int]] = None,
    hour_attempted: Optional[List[int]] = None,
    hour_copied_from_day: bool,
    capped_out: int,
    selection_policy: str,
    subnet_source: str,
    published: bool,
    timing: Dict[str, float],
    tradable_netuids: Optional[Set[int]] = None,
) -> Dict[str, Any]:
    scoring_set = membership_scoring_expected(list(receipt.get("expected_netuids") or []))
    day_block = _horizon_block(
        horizon="day",
        expected=day_expected,
        succeeded=day_succeeded,
        failed=day_failed,
        hour_copied_from_day=False,
        tradable_netuids=tradable_netuids,
        attempted_netuids=day_attempted,
    )
    hour_block = _horizon_block(
        horizon="hour",
        expected=day_expected,
        succeeded=hour_succeeded,
        failed=hour_failed,
        hour_copied_from_day=hour_copied_from_day,
        tradable_netuids=tradable_netuids,
        attempted_netuids=hour_attempted,
    )
    membership_ok = membership_allows_complete(receipt)
    hour_ok = False
    if hour_block.get("hour_copied_from_day"):
        hour_ok = hour_block.get("status") == "copied" and hour_block.get("complete") is True
    else:
        hour_ok = hour_block.get("status") == "scored" and hour_block.get("complete") is True
    horizons_complete = day_block["complete"] and hour_ok
    complete = bool(
        published
        and membership_ok
        and horizons_complete
        and capped_out == 0
    )
    return {
        "membership": receipt,
        "scoring_set_netuids": scoring_set,
        "root_netuid_in_scoring_set": 0 in scoring_set,
        "day": day_block,
        "hour": hour_block,
        "capped_out": capped_out,
        "selection_policy": selection_policy,
        "subnet_load_source": subnet_source,
        "published": published,
        "complete": complete,
        "timing": timing,
    }


def note_cycle(coverage: Dict[str, Any]) -> int:
    """Track consecutive partial cycles; return current streak length."""
    global _consecutive_partial_cycles, _last_cycle
    _last_cycle = dict(coverage)
    if coverage.get("complete"):
        _consecutive_partial_cycles = 0
    else:
        _consecutive_partial_cycles += 1
    return _consecutive_partial_cycles


def consecutive_partial_cycles() -> int:
    return _consecutive_partial_cycles


def last_coverage_snapshot() -> Dict[str, Any]:
    return dict(_last_cycle)


def clear_last_coverage_snapshot() -> None:
    """Drop in-process coverage (e.g. when disk snapshot is stale/missing)."""
    global _last_cycle
    _last_cycle = {}


def phase1_exit_gate_met() -> bool:
    """Synthetic gate helper for tests — not prod mutation."""
    return _consecutive_partial_cycles >= PHASE1_CONSECUTIVE_PARTIAL_CYCLES


def reset_phase1_cycle_state_for_tests() -> None:
    global _consecutive_partial_cycles, _last_cycle
    _consecutive_partial_cycles = 0
    _last_cycle = {}


def coverage_counts_summary(coverage: Dict[str, Any]) -> Dict[str, Any]:
    """Slim coverage for soul_map RMW — full netuid lists stay on snapshot file only."""
    if not isinstance(coverage, dict):
        return {}
    membership = coverage.get("membership") if isinstance(coverage.get("membership"), dict) else {}
    out: Dict[str, Any] = {
        "published": coverage.get("published"),
        "complete": coverage.get("complete"),
        "capped_out": coverage.get("capped_out"),
        "selection_policy": coverage.get("selection_policy"),
        "subnet_load_source": coverage.get("subnet_load_source"),
        "timing": dict(coverage.get("timing") or {}),
        "capture_reason": coverage.get("capture_reason"),
    }
    out["membership"] = {
        k: membership.get(k)
        for k in (
            "source",
            "universe_status",
            "fresh",
            "degraded",
            "cap_reached",
            "refresh_incomplete",
            "resolved_at",
        )
    }
    for horizon in ("day", "hour"):
        block = coverage.get(horizon) if isinstance(coverage.get(horizon), dict) else {}
        slim: Dict[str, Any] = {
            "attempted": block.get("attempted"),
            "succeeded_count": len(block.get("succeeded") or []),
            "failed_count": len(block.get("failed") or []),
            "skipped_invalid": block.get("skipped_invalid"),
            "complete": block.get("complete"),
        }
        if horizon == "hour":
            slim["hour_copied_from_day"] = block.get("hour_copied_from_day")
            slim["status"] = block.get("status")
        out[horizon] = slim
    return out


def coverage_capture_deadline_seconds(start_mono: float) -> bool:
    return (time.monotonic() - start_mono) <= PHASE1_COVERAGE_CAPTURE_MAX_SECONDS


def reset_score_snapshot_gauges() -> None:
    try:
        from internal.metrics import (
            SCORE_SNAPSHOT_COVERAGE_COMPLETE,
            SCORE_SNAPSHOT_COVERAGE_PUBLISHED,
            SCORE_SNAPSHOT_HORIZON_SUCCEEDED,
            SCORE_SNAPSHOT_TIMING_BUILD_SECONDS,
            SCORE_SNAPSHOT_TIMING_PUBLISH_SECONDS,
        )
    except Exception:
        return
    try:
        SCORE_SNAPSHOT_COVERAGE_COMPLETE.set(0.0)
        SCORE_SNAPSHOT_COVERAGE_PUBLISHED.set(0.0)
        SCORE_SNAPSHOT_TIMING_BUILD_SECONDS.set(0.0)
        from internal.metrics import SCORE_SNAPSHOT_TIMING_PUBLISH_UNAVAILABLE

        SCORE_SNAPSHOT_TIMING_PUBLISH_SECONDS.set(SCORE_SNAPSHOT_TIMING_PUBLISH_UNAVAILABLE)
        for horizon in ("day", "hour"):
            SCORE_SNAPSHOT_HORIZON_SUCCEEDED.labels(horizon=horizon).set(0.0)
    except Exception:
        pass


def publish_metrics(coverage: Dict[str, Any]) -> None:
    try:
        from internal.metrics import (
            SCORE_SNAPSHOT_COVERAGE_COMPLETE,
            SCORE_SNAPSHOT_COVERAGE_PUBLISHED,
            SCORE_SNAPSHOT_TIMING_BUILD_SECONDS,
            SCORE_SNAPSHOT_TIMING_PUBLISH_SECONDS,
        )
    except Exception:
        return
    timing = coverage.get("timing") or {}

    def _set(gauge, value) -> None:
        if value is None:
            return
        try:
            gauge.set(value)
        except Exception:
            pass

    from internal.metrics import SCORE_SNAPSHOT_TIMING_PUBLISH_UNAVAILABLE

    _set(SCORE_SNAPSHOT_COVERAGE_COMPLETE, 1.0 if coverage.get("complete") else 0.0)
    _set(SCORE_SNAPSHOT_COVERAGE_PUBLISHED, 1.0 if coverage.get("published") else 0.0)
    _set(SCORE_SNAPSHOT_TIMING_BUILD_SECONDS, timing.get("build_wall_seconds"))
    publish_wall = timing.get("publish_wall_seconds")
    if publish_wall is None:
        try:
            SCORE_SNAPSHOT_TIMING_PUBLISH_SECONDS.set(
                SCORE_SNAPSHOT_TIMING_PUBLISH_UNAVAILABLE
            )
        except Exception:
            pass
    else:
        _set(SCORE_SNAPSHOT_TIMING_PUBLISH_SECONDS, publish_wall)
    for horizon in ("day", "hour"):
        block = coverage.get(horizon) or {}
        try:
            from internal.metrics import SCORE_SNAPSHOT_HORIZON_SUCCEEDED

            SCORE_SNAPSHOT_HORIZON_SUCCEEDED.labels(horizon=horizon).set(
                len(block.get("succeeded") or [])
            )
        except Exception:
            pass
