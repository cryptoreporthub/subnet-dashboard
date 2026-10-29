"""Phase 1 score-snapshot coverage telemetry (honesty only — no cap policy change)."""

from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

from internal.chain_read import ChainRead
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
# Process-local publish timing (not on disk); survives disk-backed publish_metrics refresh.
_process_publish_wall_seconds: Optional[float] = None


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


def membership_generation(expected_netuids: Any) -> str:
    """Content id of the scored set. Block and rpc stay out: every refresh pins a new block."""
    body = {"v": 1, "expected_netuids": membership_scoring_expected(list(expected_netuids))}
    digest = hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    return "mg1:" + digest.hexdigest()[:16]


def load_membership_receipt() -> Dict[str, Any]:
    try:
        from internal.subnet_universe import get_snapshot, universe_snapshot_feed_meta

        snap = get_snapshot()
        feed = universe_snapshot_feed_meta(snap)
        # Owner rule: expected is exactly the pinned chain read, so a chain-unregistered netuid is
        # out at once even while its row stays in ``snap.netuids`` for the 48h grace.
        chain = snap.chain
        return {
            "source": feed.get("source"),
            "sources": list(feed.get("sources") or []),
            "resolved_at": snap.resolved_at,
            "universe_status": snap.status,
            "degraded": bool(snap.degraded),
            "cap_reached": bool(snap.cap_reached),
            "refresh_incomplete": bool(snap.refresh_incomplete),
            "expected_netuids": list(chain.netuids) if chain else [],
            "generation": membership_generation(chain.netuids if chain else []),
            "block_hash": chain.block_hash if chain else None,
            "rpc": chain.rpc if chain else None,
            "chain": chain.to_dict() if chain else None,
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
            "generation": membership_generation([]),
            "block_hash": None,
            "rpc": None,
            "chain": None,
            "fresh": False,
            "root_netuid_in_membership": False,
            "message": str(exc),
        }


def membership_scoring_expected(membership_netuids: List[int]) -> List[int]:
    """Pinned membership denominator before scoring — never tradable∩shrink."""
    return sorted({int(n) for n in membership_netuids if int(n) > 0})


def membership_scoring_candidate_rows(
    expected_netuids: List[int],
    feed_rows: List[Dict[str, Any]],
    *,
    membership_rows: Optional[List[Dict[str, Any]]] = None,
    receipt: Optional[Dict[str, Any]] = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Admission list for snapshot scoring — membership IDs, not raw feed cardinality.

    Positive membership netuids are admitted once when a tradable row exists in the
    feed or universe snapshot. Feed-only IDs (including deregistered extras) are
    excluded. Root (0) is never scored. Stale/degraded/emergency membership admits
    nothing (coverage denominator stays on the receipt). Empty membership admits
    nothing — never tradable feed fallback.
    """
    from internal.subnets.tradable import (
        is_tradable_subnet,
        normalize_subnet_row,
        subnet_netuid,
        tradable_subnets,
    )

    expected = membership_scoring_expected(expected_netuids)
    by_netuid: Dict[int, Dict[str, Any]] = {}
    for sn in feed_rows or []:
        row = normalize_subnet_row(sn)
        if not is_tradable_subnet(row):
            continue
        by_netuid[int(row["netuid"])] = row
    for sn in membership_rows or []:
        row = normalize_subnet_row(sn)
        if not is_tradable_subnet(row):
            continue
        nu = int(row["netuid"])
        if nu not in by_netuid:
            by_netuid[nu] = row

    feed_tradable_ids = {subnet_netuid(r) for r in tradable_subnets(feed_rows or [])}
    feed_tradable_ids = {int(n) for n in feed_tradable_ids if n is not None and int(n) > 0}
    expected_set = set(expected)

    pin_from_receipt = membership_scoring_expected(
        list((receipt or {}).get("expected_netuids") or expected_netuids)
    )

    if receipt is not None and not membership_allows_admission(receipt):
        gate_reason = membership_admission_block_reason(receipt)
        excluded_feed_only = sorted(feed_tradable_ids - set(pin_from_receipt))
        return [], {
            "selection_basis": "membership_gated",
            "expected_count": len(pin_from_receipt),
            "admitted_count": 0,
            "missing_netuids": list(pin_from_receipt),
            "excluded_feed_only_count": len(excluded_feed_only),
            "excluded_feed_only_netuids": excluded_feed_only[:32],
            "membership_admission_allowed": False,
            "admission_gate_reason": gate_reason,
        }

    if not expected:
        return [], {
            "selection_basis": "membership_empty",
            "expected_count": 0,
            "admitted_count": 0,
            "missing_netuids": [],
            "excluded_feed_only_count": len(feed_tradable_ids),
            "membership_admission_allowed": membership_allows_admission(receipt or {}),
        }

    candidates: List[Dict[str, Any]] = []
    missing: List[int] = []
    for netuid in expected:
        row = by_netuid.get(netuid)
        if row is None:
            missing.append(netuid)
            continue
        candidates.append(row)

    excluded_feed_only = sorted(feed_tradable_ids - expected_set)
    return candidates, {
        "selection_basis": "membership",
        "expected_count": len(expected),
        "admitted_count": len(candidates),
        "missing_netuids": missing,
        "excluded_feed_only_count": len(excluded_feed_only),
        "excluded_feed_only_netuids": excluded_feed_only[:32],
        "membership_admission_allowed": True,
    }


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


def _has_chain_provenance(receipt: Dict[str, Any]) -> bool:
    chain = ChainRead.parse(receipt.get("chain"))
    return chain is not None and chain.rpc is not None


def membership_allows_admission(receipt: Dict[str, Any]) -> bool:
    """Fail closed — score only from fresh, non-emergency, complete membership.

    ``universe_status`` must be exactly "ok". The universe provider only writes "ok", "degraded" or
    "emergency_registry" (a receipt built after an error says "unknown"), so a stale marker, a missing
    key or any other spelling is a verdict nobody can vouch for; admitting it would let an unknown
    state publish a complete snapshot. Real receipts always carry the key.
    """
    if not receipt.get("fresh"):
        return False
    if receipt.get("universe_status") != "ok":
        return False
    if receipt.get("degraded"):
        return False
    if receipt.get("cap_reached"):
        return False
    if receipt.get("refresh_incomplete"):
        return False
    return _has_chain_provenance(receipt)


def membership_admission_block_reason(receipt: Dict[str, Any]) -> Optional[str]:
    if membership_allows_admission(receipt):
        return None
    if not receipt.get("fresh"):
        return "stale_membership"
    status = str(receipt.get("universe_status") or "")
    if status == "emergency_registry":
        return "emergency_registry"
    if status == "unknown":
        return "unknown_membership"
    if receipt.get("degraded"):
        return "degraded"
    if receipt.get("cap_reached"):
        return "cap_reached"
    if receipt.get("refresh_incomplete"):
        return "refresh_incomplete"
    if receipt.get("universe_status") != "ok":
        return "universe_status_not_ok"
    if not _has_chain_provenance(receipt):
        return "membership_without_chain_provenance"
    return "membership_not_admissible"


def membership_allows_complete(receipt: Dict[str, Any]) -> bool:
    return membership_allows_admission(receipt)


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
    )
    return {
        "membership": receipt,
        "scoring_set_netuids": scoring_set,
        "root_netuid_in_scoring_set": 0 in scoring_set,
        "day": day_block,
        "hour": hour_block,
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
    global _consecutive_partial_cycles, _last_cycle, _process_publish_wall_seconds
    _consecutive_partial_cycles = 0
    _last_cycle = {}
    _process_publish_wall_seconds = None


def record_publish_wall_seconds(value: float) -> None:
    """Remember last publish duration for the next snapshot write (process-local)."""
    global _process_publish_wall_seconds
    _process_publish_wall_seconds = float(value)


def coverage_timing_for_disk(timing: Dict[str, Any]) -> Dict[str, Any]:
    """Persist build + previous publish timing; current publish stays process-only."""
    out = {k: v for k, v in (timing or {}).items() if k != "publish_wall_seconds"}
    if _process_publish_wall_seconds is not None:
        out["previous_publish_wall_seconds"] = round(_process_publish_wall_seconds, 6)
    return out


def _publish_wall_gauge_value(timing: Dict[str, Any]) -> float:
    from internal.metrics import SCORE_SNAPSHOT_TIMING_PUBLISH_UNAVAILABLE

    on_wire = timing.get("publish_wall_seconds")
    if on_wire is not None:
        return float(on_wire)
    if _process_publish_wall_seconds is not None:
        return _process_publish_wall_seconds
    prev = timing.get("previous_publish_wall_seconds")
    if prev is not None:
        return float(prev)
    return SCORE_SNAPSHOT_TIMING_PUBLISH_UNAVAILABLE


def _build_wall_gauge_value(timing: Dict[str, Any]) -> float:
    from internal.metrics import SCORE_SNAPSHOT_TIMING_BUILD_UNAVAILABLE

    build = timing.get("build_wall_seconds")
    if build is None:
        return SCORE_SNAPSHOT_TIMING_BUILD_UNAVAILABLE
    return float(build)


def _hour_block_is_copied(block: Dict[str, Any]) -> bool:
    """Honor explicit status; infer copied from legacy hour_copied_from_day when absent."""
    status = block.get("status")
    if status is not None:
        return status == "copied"
    return bool(block.get("hour_copied_from_day"))


def _horizon_scored_count(block: Dict[str, Any], horizon: str) -> int:
    succeeded = block.get("succeeded") or []
    if horizon == "hour" and _hour_block_is_copied(block):
        return 0
    return len(succeeded)


def _horizon_copied_count(block: Dict[str, Any], horizon: str) -> int:
    if horizon != "hour" or not _hour_block_is_copied(block):
        return 0
    return len(block.get("succeeded") or [])


def coverage_counts_summary(coverage: Dict[str, Any]) -> Dict[str, Any]:
    """Slim coverage for soul_map RMW — full netuid lists stay on snapshot file only."""
    if not isinstance(coverage, dict):
        return {}
    membership = coverage.get("membership") if isinstance(coverage.get("membership"), dict) else {}
    out: Dict[str, Any] = {
        "published": coverage.get("published"),
        "complete": coverage.get("complete"),
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
            SCORE_SNAPSHOT_HORIZON_COPIED,
            SCORE_SNAPSHOT_HORIZON_SUCCEEDED,
            SCORE_SNAPSHOT_TIMING_BUILD_SECONDS,
            SCORE_SNAPSHOT_TIMING_PUBLISH_SECONDS,
        )
    except Exception:
        return
    try:
        SCORE_SNAPSHOT_COVERAGE_COMPLETE.set(0.0)
        SCORE_SNAPSHOT_COVERAGE_PUBLISHED.set(0.0)
        from internal.metrics import SCORE_SNAPSHOT_TIMING_BUILD_UNAVAILABLE

        SCORE_SNAPSHOT_TIMING_BUILD_SECONDS.set(SCORE_SNAPSHOT_TIMING_BUILD_UNAVAILABLE)
        SCORE_SNAPSHOT_TIMING_PUBLISH_SECONDS.set(_publish_wall_gauge_value({}))
        for horizon in ("day", "hour"):
            SCORE_SNAPSHOT_HORIZON_SUCCEEDED.labels(horizon=horizon).set(0.0)
            SCORE_SNAPSHOT_HORIZON_COPIED.labels(horizon=horizon).set(0.0)
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

    _set(SCORE_SNAPSHOT_COVERAGE_COMPLETE, 1.0 if coverage.get("complete") else 0.0)
    _set(SCORE_SNAPSHOT_COVERAGE_PUBLISHED, 1.0 if coverage.get("published") else 0.0)
    try:
        SCORE_SNAPSHOT_TIMING_BUILD_SECONDS.set(_build_wall_gauge_value(timing))
    except Exception:
        pass
    try:
        SCORE_SNAPSHOT_TIMING_PUBLISH_SECONDS.set(_publish_wall_gauge_value(timing))
    except Exception:
        pass
    for horizon in ("day", "hour"):
        block = coverage.get(horizon) or {}
        try:
            from internal.metrics import (
                SCORE_SNAPSHOT_HORIZON_COPIED,
                SCORE_SNAPSHOT_HORIZON_SUCCEEDED,
            )

            SCORE_SNAPSHOT_HORIZON_SUCCEEDED.labels(horizon=horizon).set(
                _horizon_scored_count(block, horizon)
            )
            SCORE_SNAPSHOT_HORIZON_COPIED.labels(horizon=horizon).set(
                _horizon_copied_count(block, horizon)
            )
        except Exception:
            pass
