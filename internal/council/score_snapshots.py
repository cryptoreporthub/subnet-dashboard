"""Full-universe score snapshots off the request path (Learning Loop Phase 2).

Background job scores all tradable subnets and writes ``data/score_snapshots.json``.
Request handlers must never call full-universe scoring — they read this file
(or fall back to the existing volume/emission cap).
"""

from __future__ import annotations

import fcntl
import json
import logging
import os
import time
import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple

from internal import build_cost
from internal.council.snapshot_coverage import env_int
from internal.job_scheduler import cancel_job, schedule_in_seconds
from internal.liveness import LivenessTracker

logger = logging.getLogger(__name__)

SCORE_SNAPSHOTS_PATH = os.environ.get(
    "SCORE_SNAPSHOTS_PATH", os.path.join("data", "score_snapshots.json")
)
SCORE_SNAPSHOT_REFRESH_MINUTES = int(os.environ.get("SCORE_SNAPSHOT_REFRESH_MINUTES", "30"))
SCORE_SNAPSHOT_MAX_AGE_SECONDS = int(os.environ.get("SCORE_SNAPSHOT_MAX_AGE_SECONDS", "7200"))
SCORE_SNAPSHOT_FIRST_DELAY_SECONDS = int(os.environ.get("SCORE_SNAPSHOT_FIRST_DELAY_SECONDS", "90"))
SCORE_SNAPSHOT_STUCK_SECONDS = int(os.environ.get("SCORE_SNAPSHOT_STUCK_SECONDS", "900"))
SCORE_SNAPSHOT_WRITE_TIMEOUT_SECONDS = int(
    os.environ.get("SCORE_SNAPSHOT_WRITE_TIMEOUT_SECONDS", "600")
)
SCORE_SNAPSHOT_SCORE_WORKERS = max(1, env_int("SCORE_SNAPSHOT_SCORE_WORKERS", 1))
SCORE_SNAPSHOT_PROGRESS_MIN_SECONDS = env_int("SCORE_SNAPSHOT_PROGRESS_MIN_SECONDS", 15)
JOB_ID = "score-snapshot-scheduler"


_lock = threading.Lock()
_TICK_ACTIVE = False
_write_executor: Optional[ThreadPoolExecutor] = None
_write_future: Optional[Any] = None
_scheduler: Optional["ScoreSnapshotScheduler"] = None


def _write_future_active() -> bool:
    fut = _write_future
    return fut is not None and not fut.done()


def _scoring_write_in_progress() -> bool:
    with _lock:
        return _write_future_active()


def _release_write_future(done_fut: Any) -> None:
    global _write_future
    with _lock:
        if _write_future is done_fut:
            _write_future = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_iso(value: Any) -> Optional[datetime]:
    if not value or not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _snapshot_stamp(payload: Optional[Dict[str, Any]]) -> Optional[datetime]:
    """Build start when present; legacy files only have written_at."""
    if not isinstance(payload, dict):
        return None
    return _parse_iso(payload.get("build_started_at")) or _parse_iso(payload.get("written_at"))


def snapshot_age_seconds(path: Optional[str] = None) -> Optional[float]:
    """Age for the 7200s freshness gate.

    A snapshot that records build_started_at is as old as the scoring run,
    not as young as the file mtime of a late publish. Legacy files without
    that field keep the mtime clock so an old written_at on a fresh file
    stays readable.
    """
    snap_path = path or SCORE_SNAPSHOTS_PATH
    snap = load_score_snapshot(snap_path)
    started = _parse_iso((snap or {}).get("build_started_at")) if snap else None
    if started is not None:
        return max(0.0, datetime.now(timezone.utc).timestamp() - started.timestamp())
    try:
        return max(0.0, datetime.now(timezone.utc).timestamp() - os.path.getmtime(snap_path))
    except OSError:
        return None


@contextmanager
def _locked_score_snapshot(snap_path: str, timeout_seconds: float = 5.0) -> Iterator[None]:
    lock_path = snap_path + ".lock"
    os.makedirs(os.path.dirname(lock_path) or ".", exist_ok=True)
    with open(lock_path, "a+", encoding="utf-8") as lock_file:
        deadline = time.monotonic() + timeout_seconds
        acquired = False
        while time.monotonic() < deadline:
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                break
            except (BlockingIOError, OSError):
                time.sleep(0.01)
        if not acquired:
            raise TimeoutError(
                f"Timed out after {timeout_seconds}s waiting for {lock_path}"
            )
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def load_score_snapshot(path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    snap_path = path or SCORE_SNAPSHOTS_PATH
    try:
        with open(snap_path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def save_score_snapshot(payload: Dict[str, Any], path: Optional[str] = None) -> Dict[str, Any]:
    snap_path = path or SCORE_SNAPSHOTS_PATH
    os.makedirs(os.path.dirname(snap_path) or ".", exist_ok=True)
    with _locked_score_snapshot(snap_path):
        publish_started = time.monotonic()
        current = load_score_snapshot(snap_path)
        incoming = _snapshot_stamp(payload)
        on_disk = _snapshot_stamp(current)
        if incoming is not None and on_disk is not None and incoming < on_disk:
            logger.info(
                "score snapshot publish skipped: incoming %s is older than on-disk %s",
                payload.get("build_started_at") or payload.get("written_at"),
                (current or {}).get("build_started_at") or (current or {}).get("written_at"),
            )
            publish_wall = time.monotonic() - publish_started
            return {
                "published": False,
                "skipped_older": True,
                "timing": {"publish_wall_seconds": round(publish_wall, 6)},
            }
        tmp = snap_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
        os.replace(tmp, snap_path)
        publish_wall = time.monotonic() - publish_started
        return {
            "published": True,
            "skipped_older": False,
            "timing": {"publish_wall_seconds": round(publish_wall, 6)},
        }


def _patch_score_snapshot_coverage_locked(
    snap_path: str,
    coverage_patch: Dict[str, Any],
) -> Dict[str, Any]:
    """One locked os.replace: merge coverage only; scored day/hour rows unchanged (#1361)."""
    with _locked_score_snapshot(snap_path):
        publish_started = time.monotonic()
        current = load_score_snapshot(snap_path)
        if not isinstance(current, dict):
            publish_wall = time.monotonic() - publish_started
            return {
                "published": False,
                "skipped_older": False,
                "timing": {"publish_wall_seconds": round(publish_wall, 6)},
            }
        merged_coverage = dict(current.get("coverage") or {})
        merged_coverage.update(coverage_patch)
        current = {**current, "coverage": merged_coverage}
        tmp = snap_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(current, handle, indent=2)
        os.replace(tmp, snap_path)
        publish_wall = time.monotonic() - publish_started
        return {
            "published": False,
            "skipped_older": False,
            "timing": {"publish_wall_seconds": round(publish_wall, 6)},
        }


def _read_complete_snapshot(
    path: Optional[str] = None,
    max_age_seconds: Optional[int] = None,
) -> Optional[Tuple[Dict[str, Any], float]]:
    age = snapshot_age_seconds(path)
    ttl = SCORE_SNAPSHOT_MAX_AGE_SECONDS if max_age_seconds is None else max_age_seconds
    if age is None or age > ttl:
        return None
    snap = load_score_snapshot(path)
    if not snap:
        return None
    coverage = snap.get("coverage") if isinstance(snap.get("coverage"), dict) else {}
    return (snap, age) if coverage.get("complete") is True else None


def _rank_by_scores(
    snap: Dict[str, Any], subnets: List[Dict[str, Any]], horizon: str
) -> Optional[List[Dict[str, Any]]]:
    scores: Dict[int, float] = {}
    for row in snap.get(horizon) or snap.get("day") or []:
        if not isinstance(row, dict):
            continue
        try:
            scores[int(row["netuid"])] = float(row.get("total_score") or 0)
        except (TypeError, ValueError, KeyError):
            continue
    if not scores:
        return None

    def _key(s: Dict[str, Any]) -> Tuple[float, float]:
        try:
            netuid = int(s.get("netuid") or 0)
        except (TypeError, ValueError):
            netuid = 0
        return (scores.get(netuid, -1.0), float(s.get("emission") or 0))

    return sorted(subnets, key=_key, reverse=True)


def rank_subnets_by_snapshot(
    subnets: List[Dict[str, Any]],
    *,
    horizon: str = "day",
    max_age_seconds: Optional[int] = None,
    path: Optional[str] = None,
) -> Optional[List[Dict[str, Any]]]:
    """Return subnets sorted by snapshot score, or None if the snapshot is missing, stale or partial."""
    got = _read_complete_snapshot(path, max_age_seconds)
    return _rank_by_scores(got[0], subnets, horizon) if got else None


def _subnets_by_netuid(subnets: List[Dict[str, Any]]) -> Dict[int, Dict[str, Any]]:
    out: Dict[int, Dict[str, Any]] = {}
    for sn in subnets:
        try:
            out[int(sn.get("netuid") or sn.get("id") or 0)] = sn
        except (TypeError, ValueError):
            continue
    return out


def _confidence_fields(source: Dict[str, Any]) -> Dict[str, Any]:
    """Real 0-1 confidence and scenario tags from a day score or snapshot row.

    A field the source does not have, or a confidence outside 0 to 1, is left out.
    Never default confidence to the 0-100 score, because the cockpit would show it
    as a different quantity.
    """
    out: Dict[str, Any] = {}
    confidence = source.get("confidence")
    if (
        isinstance(confidence, (int, float))
        and not isinstance(confidence, bool)
        and 0.0 <= confidence <= 1.0
    ):
        out["confidence"] = float(confidence)
    tags = source.get("scenario_tags")
    if isinstance(tags, dict):
        out["scenario_tags"] = tags
    return out


def _top_pick_row(
    row: Dict[str, Any],
    subnets_by_netuid: Dict[int, Dict[str, Any]],
) -> Dict[str, Any]:
    try:
        netuid = int(row["netuid"])
    except (TypeError, ValueError, KeyError):
        return {}
    sn = subnets_by_netuid.get(netuid, {})
    total = float(row.get("total_score") or 0)
    return {
        "netuid": netuid,
        "name": sn.get("name") or row.get("name"),
        "symbol": sn.get("symbol"),
        "score": total,
        "expert_contributions": {},
        "signals": {
            "price_change_24h": sn.get("price_change_24h"),
            "price_change_7d": sn.get("price_change_7d"),
            "emission": sn.get("emission"),
            "apy": sn.get("apy"),
            "volume": sn.get("volume"),
        },
        "scenario_tags": {},
        "recovery_context": row.get("recovery_context"),
        **_confidence_fields(row),
    }


def build_top_picks_from_snapshot(
    subnets: Optional[List[Dict[str, Any]]] = None,
    *,
    max_age_seconds: Optional[int] = None,
    limit: int = 3,
    path: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Read top hour/day picks from disk snapshot — no scoring on the request path."""
    got = _read_complete_snapshot(path, max_age_seconds)
    if got is None:
        return None
    snap, age = got
    hour_rows = [r for r in (snap.get("hour") or []) if isinstance(r, dict)]
    day_rows = [r for r in (snap.get("day") or []) if isinstance(r, dict)]
    if not hour_rows and not day_rows:
        return None
    hour_rows.sort(key=lambda r: float(r.get("total_score") or 0), reverse=True)
    day_rows.sort(key=lambda r: float(r.get("total_score") or 0), reverse=True)
    if subnets is None:
        subnets = []
    by_netuid = _subnets_by_netuid(subnets)
    hour_picks = [_top_pick_row(r, by_netuid) for r in hour_rows[:limit]]
    day_picks = [_top_pick_row(r, by_netuid) for r in day_rows[:limit]]
    hour_picks = [p for p in hour_picks if p]
    day_picks = [p for p in day_picks if p]
    if not hour_picks and not day_picks:
        return None
    return {
        "hour_picks": hour_picks,
        "day_picks": day_picks,
        "meta": {
            "source": "score_snapshot",
            "snapshot_age_seconds": round(age, 3),
            "count_hour": len(hour_rows),
            "count_day": len(day_rows),
        },
    }


def day_scored_from_snapshot(
    subnets: List[Dict[str, Any]],
    *,
    max_age_seconds: Optional[int] = None,
    path: Optional[str] = None,
) -> Optional[List[Dict[str, Any]]]:
    """Join tradable subnets to day scores from snapshot (minimal score payloads)."""
    got = _read_complete_snapshot(path, max_age_seconds)
    if got is None:
        return None
    snap = got[0]
    ranked = _rank_by_scores(snap, subnets, "day")
    if ranked is None:
        return None
    scores: Dict[int, Dict[str, Any]] = {}
    for row in snap.get("day") or []:
        if not isinstance(row, dict):
            continue
        try:
            netuid = int(row["netuid"])
        except (TypeError, ValueError, KeyError):
            continue
        scores[netuid] = row
    out: List[Dict[str, Any]] = []
    for sn in ranked:
        try:
            netuid = int(sn.get("netuid") or 0)
        except (TypeError, ValueError):
            continue
        row = scores.get(netuid)
        if not row:
            continue
        total = float(row.get("total_score") or 0)
        out.append(
            {
                "subnet": sn,
                "score": {
                    "total_score": total,
                    "expert_contributions": {},
                    "scenario_tags": {},
                    "recovery_context": row.get("recovery_context"),
                    "reasons": [],
                    **_confidence_fields(row),
                },
            }
        )
    return out if out else None


def _load_pump_ladder_state_for_build() -> Dict[str, Any]:
    """One disk read per snapshot build; not cached across builds."""
    try:
        from internal.pump.state import load_state

        st = load_state()
        return st if isinstance(st, dict) else {"subnets": {}, "meta": {}}
    except Exception:
        return {"version": "1.0", "subnets": {}, "meta": {}}


_SLOWEST_NETUID_SAMPLES = 8


def build_full_universe_snapshot(
    subnets: List[Dict[str, Any]],
    market_context: Optional[Dict[str, Any]] = None,
    *,
    score_hour: Optional[bool] = None,
    progress_cb: Optional[Callable[[int, int], None]] = None,
) -> Dict[str, Any]:
    """Score every subnet (background only). Returns serializable snapshot."""
    from internal.council.state_vector import score_subnet_for_day, score_subnet_for_hour
    from internal.subnets.tradable import tradable_subnets

    if score_hour is None:
        score_hour = _score_hour_enabled()
    pump_load_started = time.monotonic()
    from internal.council.scoring_context import enrich_scoring_market_context

    build_context = enrich_scoring_market_context(market_context)
    build_context["pump_ladder_state"] = _load_pump_ladder_state_for_build()
    pump_load_seconds = time.monotonic() - pump_load_started
    rows = tradable_subnets(subnets) if subnets else []
    build_started_at = _now_iso()
    hour_rows: List[Dict[str, Any]] = []
    day_rows: List[Dict[str, Any]] = []
    day_failed: List[Dict[str, Any]] = []
    hour_failed: List[Dict[str, Any]] = []
    day_succeeded: List[int] = []
    hour_succeeded: List[int] = []
    day_attempted: List[int] = []
    hour_attempted: List[int] = []
    skipped_invalid = 0
    total = len(rows)
    subnet_loop_started = time.monotonic()
    day_scoring_seconds = 0.0
    hour_scoring_seconds = 0.0
    slowest_day: List[Tuple[float, int]] = []

    def _record_slowest(day_elapsed: float, netuid: int) -> None:
        if len(slowest_day) < _SLOWEST_NETUID_SAMPLES:
            slowest_day.append((day_elapsed, netuid))
            slowest_day.sort(reverse=True)
        elif day_elapsed > slowest_day[-1][0]:
            slowest_day[-1] = (day_elapsed, netuid)
            slowest_day.sort(reverse=True)

    def _score_one(sn: Dict[str, Any]) -> Dict[str, Any]:
        try:
            netuid = int(sn.get("netuid"))
        except (TypeError, ValueError):
            return {"skip": True}
        out: Dict[str, Any] = {
            "netuid": netuid,
            "day_elapsed": 0.0,
            "hour_elapsed": 0.0,
        }
        if score_hour:
            hour_started = time.monotonic()
            try:
                h = score_subnet_for_hour(sn, build_context)
                out["hour_row"] = {
                    "netuid": netuid,
                    "total_score": float(h.get("total_score") or 0),
                    "name": sn.get("name"),
                    "recovery_context": h.get("recovery_context"),
                    **_confidence_fields(h),
                }
                out["hour_ok"] = True
            except Exception as exc:
                out["hour_fail"] = {
                    "netuid": netuid,
                    "stage": "hour",
                    "error_class": type(exc).__name__,
                }
            out["hour_elapsed"] = time.monotonic() - hour_started
        day_started = time.monotonic()
        try:
            d = score_subnet_for_day(sn, build_context)
            out["day_row"] = {
                "netuid": netuid,
                "total_score": float(d.get("total_score") or 0),
                "name": sn.get("name"),
                "recovery_context": d.get("recovery_context"),
                **_confidence_fields(d),
            }
            out["day_ok"] = True
        except Exception as exc:
            out["day_fail"] = {
                "netuid": netuid,
                "stage": "day",
                "error_class": type(exc).__name__,
            }
        out["day_elapsed"] = time.monotonic() - day_started
        return out

    def _apply_score_result(res: Dict[str, Any]) -> None:
        nonlocal skipped_invalid, day_scoring_seconds, hour_scoring_seconds
        if res.get("skip"):
            skipped_invalid += 1
            return
        netuid = res["netuid"]
        if score_hour:
            hour_attempted.append(netuid)
            hour_scoring_seconds += float(res.get("hour_elapsed") or 0)
            if res.get("hour_ok"):
                hour_rows.append(res["hour_row"])
                hour_succeeded.append(netuid)
            elif res.get("hour_fail"):
                hour_failed.append(res["hour_fail"])
        day_attempted.append(netuid)
        day_scoring_seconds += float(res.get("day_elapsed") or 0)
        if res.get("day_ok"):
            day_rows.append(res["day_row"])
            day_succeeded.append(netuid)
        elif res.get("day_fail"):
            day_failed.append(res["day_fail"])
        _record_slowest(float(res.get("day_elapsed") or 0), netuid)

    workers = SCORE_SNAPSHOT_SCORE_WORKERS if not score_hour else 1
    last_progress = time.monotonic()

    def _maybe_progress(done: int) -> None:
        nonlocal last_progress
        if progress_cb and total and time.monotonic() - last_progress >= SCORE_SNAPSHOT_PROGRESS_MIN_SECONDS:
            last_progress = time.monotonic()
            progress_cb(done, total)

    if workers <= 1:
        for idx, sn in enumerate(rows):
            _apply_score_result(_score_one(sn))
            _maybe_progress(idx + 1)
    else:
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="snap-score") as pool:
            results = list(pool.map(_score_one, rows))
        for idx, res in enumerate(results):
            _apply_score_result(res)
            _maybe_progress(idx + 1)

    hour_copied_from_day = False
    if not score_hour and day_rows:
        hour_copied_from_day = True
        hour_rows = [{**row, "source": "copied_from_day"} for row in day_rows]
        hour_succeeded = list(day_succeeded)
        hour_failed = []
        hour_attempted = []

    hour_rows.sort(key=lambda r: r["total_score"], reverse=True)
    day_rows.sort(key=lambda r: r["total_score"], reverse=True)
    subnet_scoring_loop_wall_seconds = time.monotonic() - subnet_loop_started
    build_stage_timing = {
        "pump_state_load_seconds": round(pump_load_seconds, 6),
        "day_scoring_seconds": round(day_scoring_seconds, 6),
        "hour_scoring_seconds": round(hour_scoring_seconds, 6),
        "subnet_scoring_loop_wall_seconds": round(subnet_scoring_loop_wall_seconds, 6),
        "score_workers": workers,
        "slowest_day_netuids": [
            {"netuid": nu, "seconds": round(sec, 6)}
            for sec, nu in slowest_day
        ],
    }
    return {
        "build_started_at": build_started_at,
        "written_at": _now_iso(),
        "count": len(rows),
        "hour": hour_rows,
        "day": day_rows,
        "build_stage_timing": build_stage_timing,
        "_coverage_inputs": {
            "day_succeeded": day_succeeded,
            "day_failed": day_failed,
            "hour_succeeded": hour_succeeded,
            "hour_failed": hour_failed,
            "hour_copied_from_day": hour_copied_from_day,
            "day_attempted": day_attempted,
            "hour_attempted": hour_attempted,
            "skipped_invalid": skipped_invalid,
            "tradable_rows": rows,
        },
    }


def _registry_only_snapshot() -> bool:
    """Background snapshot defaults to registry rows — fast, no outbound wedge."""
    default = "on"
    try:
        from internal.run_mode import is_worker_mode

        if is_worker_mode():
            default = "on"
    except Exception:
        pass
    flag = os.environ.get("SCORE_SNAPSHOT_REGISTRY_ONLY", default).strip().lower()
    return flag in ("1", "true", "yes", "on")


def _score_hour_enabled() -> bool:
    """Hour scoring doubles CPU on worker — day-only is enough for ranking."""
    default = "off"
    try:
        from internal.run_mode import is_worker_mode

        if is_worker_mode():
            default = "off"
    except Exception:
        pass
    flag = os.environ.get("SCORE_SNAPSHOT_SCORE_HOUR", default).strip().lower()
    return flag in ("1", "true", "yes", "on")


def _receipt_line(build_id: str, timing: Dict[str, Any], outcome: Dict[str, Any]) -> str:
    # previous_publish_wall_seconds belongs to the prior build; leave it off this build's line.
    body = {k: v for k, v in timing.items() if k != "previous_publish_wall_seconds"}
    return "score snapshot build receipt build_id=%s %s" % (
        build_id,
        json.dumps({**body, **outcome}, default=str, sort_keys=True),
    )


def _log_build_receipt(build_id: str, timing: Dict[str, Any], **outcome: Any) -> None:
    """One INFO line with the timing block and the publish outcome. Never raises:
    a logging problem must not suppress a snapshot that was already written."""
    try:
        logger.info(_receipt_line(build_id, timing, outcome))
    except Exception:
        logger.warning("score snapshot build receipt could not be logged", exc_info=True)


def write_full_universe_snapshot(
    progress_cb: Optional[Callable[[int, int], None]] = None,
) -> Dict[str, Any]:
    """Load subnets, score, persist. Call only from background."""
    capture_started = time.monotonic()
    prep_meta: Dict[str, Any] = {}
    write_stage_timing: Dict[str, Any] = {}
    receipt: Dict[str, Any] = {}
    try:
        from server import _get_subnets_hydrate, _get_subnets_with_source, _market_context_with_weights

        from internal.council.snapshot_coverage import (
            load_membership_receipt,
            membership_scoring_candidate_rows,
        )

        load_started = time.monotonic()
        if _registry_only_snapshot():
            feed_subnets, source = _get_subnets_hydrate()
        else:
            feed_subnets, source = _get_subnets_with_source(timeout=20)
            if not feed_subnets:
                feed_subnets, source = _get_subnets_hydrate()
        write_stage_timing["subnet_load_seconds"] = round(time.monotonic() - load_started, 6)

        receipt = load_membership_receipt()
        prep_started = time.monotonic()
        membership_rows: List[Dict[str, Any]] = []
        # Registry-only hydrate is the scoring input cap; universe rows backfill live feeds only.
        if not _registry_only_snapshot():
            try:
                from internal.subnet_universe import get_snapshot

                snap = get_snapshot()
                membership_rows = list(snap.rows) if snap is not None else []
            except Exception:
                membership_rows = []
        subnets, prep_meta = membership_scoring_candidate_rows(
            list(receipt.get("expected_netuids") or []),
            feed_subnets or [],
            membership_rows=membership_rows,
            receipt=receipt,
        )
        write_stage_timing["candidate_prep_seconds"] = round(time.monotonic() - prep_started, 6)
        write_stage_timing["membership_expected_count"] = int(prep_meta.get("expected_count") or 0)
        write_stage_timing["membership_admitted_count"] = int(prep_meta.get("admitted_count") or 0)
        write_stage_timing["excluded_feed_only_count"] = int(
            prep_meta.get("excluded_feed_only_count") or 0
        )

        selection_policy = str(prep_meta.get("selection_basis") or "full")
        ctx_started = time.monotonic()
        from internal.council.scoring_context import enrich_scoring_market_context

        ctx = enrich_scoring_market_context(_market_context_with_weights(subnets or []))
        write_stage_timing["market_context_seconds"] = round(time.monotonic() - ctx_started, 6)
        logger.info(
            "score snapshot build started: source=%s registry_only=%s feed_rows=%d admitted=%d expected=%d",
            source,
            _registry_only_snapshot(),
            len(feed_subnets or []),
            len(subnets or []),
            write_stage_timing.get("membership_expected_count"),
        )
    except Exception as exc:
        return {"ok": False, "error": f"subnet load: {exc}"}

    def _build_and_save(build_id: str) -> Dict[str, Any]:
        from internal.council.snapshot_coverage import (
            build_coverage_block,
            coverage_capture_deadline_seconds,
            coverage_timing_for_disk,
            record_publish_wall_seconds,
            membership_scoring_expected,
            note_cycle,
            publish_metrics,
            tradable_netuid_set,
        )

        expected = membership_scoring_expected(list(receipt.get("expected_netuids") or []))
        build_started = time.monotonic()
        build_cost.begin(build_id)
        try:
            payload = build_full_universe_snapshot(
                subnets or [],
                ctx,
                progress_cb=progress_cb,
            )
        finally:
            cost = build_cost.end()
        build_wall = time.monotonic() - build_started
        inputs = payload.pop("_coverage_inputs", {}) or {}
        stage_timing = payload.pop("build_stage_timing", None)
        tradable_ids = tradable_netuid_set(list(inputs.get("tradable_rows") or []))
        timing: Dict[str, Any] = {
            "build_wall_seconds": round(build_wall, 6),
            "capture_elapsed_seconds": round(time.monotonic() - capture_started, 6),
        }
        timing.update(write_stage_timing)
        if cost:
            timing["build_cost"] = cost
        if isinstance(stage_timing, dict):
            timing.update(stage_timing)
        try:
            coverage = build_coverage_block(
                receipt=receipt,
                day_expected=expected,
                day_succeeded=list(inputs.get("day_succeeded") or []),
                day_failed=list(inputs.get("day_failed") or []),
                hour_succeeded=list(inputs.get("hour_succeeded") or []),
                hour_failed=list(inputs.get("hour_failed") or []),
                day_attempted=list(inputs.get("day_attempted") or []),
                hour_attempted=list(inputs.get("hour_attempted") or []),
                hour_copied_from_day=bool(inputs.get("hour_copied_from_day")),
                selection_policy=selection_policy,
                subnet_source=str(source),
                published=True,
                timing=timing,
                tradable_netuids=tradable_ids,
            )
        except Exception as exc:
            coverage = {
                "membership": receipt,
                "published": True,
                "complete": False,
                "capture_reason": "coverage_assembly_error",
                "coverage_error": str(exc),
                "timing": timing,
            }
        if prep_meta.get("membership_admission_allowed") is not None:
            coverage["membership_admission_allowed"] = bool(
                prep_meta.get("membership_admission_allowed")
            )
        gate_reason = prep_meta.get("admission_gate_reason")
        if gate_reason:
            coverage["membership_admission_gate_reason"] = str(gate_reason)
        if int(inputs.get("skipped_invalid") or 0):
            coverage["skipped_invalid"] = int(inputs["skipped_invalid"])
        capture_timed_out = not coverage_capture_deadline_seconds(capture_started)
        if capture_timed_out:
            coverage["complete"] = False
            coverage["capture_reason"] = "capture_timeout"
        # MC: previous_publish_wall_seconds is embedded here — one locked os.replace only.
        disk_timing = coverage_timing_for_disk(timing)
        coverage["timing"] = disk_timing
        gated_empty = (
            prep_meta.get("membership_admission_allowed") is False
            and not (payload.get("day") or payload.get("hour"))
        )
        existing_on_disk = load_score_snapshot(SCORE_SNAPSHOTS_PATH) if gated_empty else None
        retain_prior = bool(
            gated_empty
            and existing_on_disk
            and (existing_on_disk.get("day") or existing_on_disk.get("hour"))
        )
        if retain_prior:
            coverage["capture_reason"] = "membership_gated_skip_publish"
            coverage["published"] = False
            coverage["complete"] = False
            prior_timing = dict(
                ((existing_on_disk or {}).get("coverage") or {}).get("timing") or {}
            )
            prior_timing.update(disk_timing)
            coverage["timing"] = prior_timing
            coverage_patch: Dict[str, Any] = {
                "complete": False,
                "published": False,
                "membership_admission_allowed": False,
                "capture_reason": "membership_gated_skip_publish",
                "timing": prior_timing,
            }
            if gate_reason:
                coverage_patch["membership_admission_gate_reason"] = str(gate_reason)
            publish_result = _patch_score_snapshot_coverage_locked(
                SCORE_SNAPSHOTS_PATH,
                coverage_patch,
            )
        else:
            publish_result = save_score_snapshot(
                {**payload, "source": source, "coverage": coverage}
            )
        published = bool(publish_result.get("published"))
        skipped_older = bool(publish_result.get("skipped_older"))
        publish_wall = (publish_result.get("timing") or {}).get("publish_wall_seconds")
        if published and publish_wall is not None:
            record_publish_wall_seconds(float(publish_wall))
        timing_for_metrics = dict(disk_timing)
        if published and publish_wall is not None:
            timing_for_metrics["publish_wall_seconds"] = publish_wall
        coverage["timing"] = timing_for_metrics
        if not published:
            coverage["published"] = False
            coverage["complete"] = False
        note_cycle(coverage)
        try:
            publish_metrics(coverage)
        except Exception:
            pass
        _log_build_receipt(
            build_id,
            timing_for_metrics,
            published=published,
            complete=bool(coverage.get("complete")),
            count=payload.get("count"),
        )
        payload["source"] = source
        payload["coverage"] = coverage
        out: Dict[str, Any] = {
            "ok": published,
            "published": published,
            "skipped_older": skipped_older,
            "complete": bool(coverage.get("complete")),
            "coverage": coverage,
            "count": payload.get("count"),
            "written_at": payload.get("written_at"),
            "path": SCORE_SNAPSHOTS_PATH,
        }
        if capture_timed_out and published:
            out["error"] = "coverage_capture_timeout"
        return out

    timeout = SCORE_SNAPSHOT_WRITE_TIMEOUT_SECONDS
    if timeout <= 0:
        try:
            return _build_and_save(_now_iso())
        except Exception as exc:
            logger.warning("score snapshot write failed: %s", exc)
            return {"ok": False, "error": str(exc)}

    global _write_executor, _write_future
    build_started_mono = time.monotonic()
    build_started_wall = _now_iso()
    caller_abandoned = threading.Event()
    with _lock:
        if _write_future is not None and not _write_future.done():
            return {"ok": False, "error": "scoring_in_progress"}
        if _write_executor is None:
            _write_executor = ThreadPoolExecutor(
                max_workers=1, thread_name_prefix="score-snap-write"
            )
        fut = _write_executor.submit(_build_and_save, build_started_wall)
        _write_future = fut
    fut.add_done_callback(_release_write_future)

    def _log_build_completion(done_fut: Any) -> None:
        """Log builds that outlive their caller-side timeout.

        The caller may abandon the wait while the single-flight build continues.
        The snapshot write is atomic and idempotent, so late completion is benign
        with respect to corruption, but it can create staleness drift. The
        duration and start timestamp make a slow crawl visible.
        """
        duration_s = time.monotonic() - build_started_mono

        if done_fut.cancelled():
            logger.warning(
                "score snapshot build failed: state=cancelled duration=%.1fs started_at=%s",
                duration_s,
                build_started_wall,
            )
            return

        try:
            err = done_fut.exception(timeout=0)
        except Exception as exc:
            logger.warning(
                "score snapshot build failed: state=callback-error duration=%.1fs "
                "started_at=%s error=%s",
                duration_s,
                build_started_wall,
                exc,
            )
            return

        if err is not None:
            logger.warning(
                "score snapshot build failed: duration=%.1fs started_at=%s error=%s",
                duration_s,
                build_started_wall,
                err,
            )
            return

        state = (
            "completed-after-abandon"
            if caller_abandoned.is_set()
            else "completed"
        )
        logger.info(
            "score snapshot build %s: duration=%.1fs started_at=%s",
            state,
            duration_s,
            build_started_wall,
        )

    fut.add_done_callback(_log_build_completion)
    try:
        return fut.result(timeout=timeout)
    except FuturesTimeoutError:
        caller_abandoned.set()
        logger.warning(
            "score snapshot build timed out after %ds "
            "(build continues in background)",
            timeout,
        )
        return {"ok": False, "error": f"write_timeout_{timeout}s"}
    except Exception as exc:
        logger.warning("score snapshot write failed: %s", exc)
        return {"ok": False, "error": str(exc)}
    finally:
        with _lock:
            if _write_future is fut and fut.done():
                _write_future = None


class ScoreSnapshotScheduler:
    def __init__(self, refresh_minutes: int = SCORE_SNAPSHOT_REFRESH_MINUTES) -> None:
        self.refresh_minutes = max(10, min(int(refresh_minutes), 24 * 60))
        self._tick_active = False
        self._last_tick_at: Optional[str] = None
        self._last_error: Optional[str] = None
        self._last_result: Dict[str, Any] = {}
        self.liveness = LivenessTracker(
            name="score_snapshot",
            interval_seconds=max(60, self.refresh_minutes * 60),
            staleness_factor=2,
            persist=True,
        )

    def _is_registered(self) -> bool:
        with _lock:
            return _scheduler is self

    def start(self, immediate: bool = False) -> Dict[str, Any]:
        if not self._is_registered():
            return {"started": False, "reason": "not registered"}
        already = self.liveness.snapshot().get("lifecycle") == "started"
        self.liveness.start()
        if immediate:
            threading.Thread(target=self._tick, daemon=True, name="score-snap-tick").start()
        else:
            # After pick schedulers; full score is the heavy job.
            # Persisted lifecycle=started is not proof a DateTrigger is armed
            # (new process generation after prior boot).
            schedule_in_seconds(JOB_ID, self._tick, SCORE_SNAPSHOT_FIRST_DELAY_SECONDS)
        if already:
            return {"started": False, "reason": "already running"}
        return {"started": True, "refresh_minutes": self.refresh_minutes}

    def stop(self) -> Dict[str, Any]:
        cancel_job(JOB_ID)
        return {"stopped": True}

    def state(self) -> Dict[str, Any]:
        snap = self.liveness.snapshot()
        return {
            "running": snap.get("lifecycle") == "started",
            "refresh_minutes": self.refresh_minutes,
            "last_run_at": self._last_tick_at,
            "last_run_error": self._last_error,
            "last_result": self._last_result,
            "age_seconds": snapshot_age_seconds(),
            "liveness": snap,
        }

    def run_once(self) -> Dict[str, Any]:
        return self._tick(reschedule=False)

    def _scoring_in_progress(self) -> bool:
        if _scoring_write_in_progress() or _TICK_ACTIVE or self._tick_active:
            return True
        try:
            from internal.council import weights

            sched = weights._load_raw().get("score_snapshot_scheduler") or {}
            last = sched.get("last_cycle") if isinstance(sched, dict) else {}
            if not isinstance(last, dict) or last.get("phase") != "scoring":
                return False
            tick = _parse_iso(last.get("run_at"))
            if tick is None:
                return False
            age = max(0.0, (datetime.now(timezone.utc) - tick).total_seconds())
            return age < SCORE_SNAPSHOT_STUCK_SECONDS
        except Exception:
            return False

    def _clear_stuck_scoring(self) -> None:
        try:
            from internal.council import weights

            sched = weights._load_raw().get("score_snapshot_scheduler") or {}
            last = sched.get("last_cycle") if isinstance(sched, dict) else {}
            if not isinstance(last, dict) or last.get("phase") != "scoring":
                return
            tick = _parse_iso(last.get("run_at"))
            if tick is None:
                return
            age = max(0.0, (datetime.now(timezone.utc) - tick).total_seconds())
            if age >= SCORE_SNAPSHOT_STUCK_SECONDS:
                self._persist_cycle_summary(
                    {
                        "run_at": _now_iso(),
                        "ok": False,
                        "error": "scoring_stuck_timeout",
                        "phase": "failed",
                    }
                )
        except Exception:
            pass

    def _record_liveness(self, result: Dict[str, Any]) -> None:
        skipped = result.get("skipped")
        if skipped:
            self.liveness.record_skip(str(skipped))
            return
        if result.get("skipped_older"):
            self.liveness.record_skip("skipped_older")
            return
        if result.get("published"):
            evidence = {
                "count": result.get("count", 0),
                "path": result.get("path") or SCORE_SNAPSHOTS_PATH,
                "op": "score_snapshot",
            }
            coverage = result.get("coverage")
            if isinstance(coverage, dict):
                from internal.council.snapshot_coverage import coverage_counts_summary

                evidence["coverage"] = coverage_counts_summary(coverage)
                evidence["coverage"]["complete"] = coverage.get("complete")
            self.liveness.record_success(evidence=evidence)
            return
        self.liveness.record_failure(
            error=str(result.get("error") or "score_snapshot_unpublished")
        )

    def _tick(self, reschedule: bool = True) -> Dict[str, Any]:
        from internal.heavy_job_gate import heavy_job_slot

        if self._scoring_in_progress():
            skipped = {"ok": False, "run_at": _now_iso(), "skipped": "scoring_in_progress"}
            # ponytail: skip persist while body runs — would drop phase=scoring and hide in-flight work
            if not self._tick_active:
                self._persist_cycle_summary(skipped)
                self._record_liveness(skipped)
            if reschedule and self._is_registered():
                schedule_in_seconds(JOB_ID, self._tick, min(120, self.refresh_minutes * 60))
            return skipped

        with heavy_job_slot("score_snapshot") as acquired:
            if not acquired:
                skipped = {"ok": False, "run_at": _now_iso(), "skipped": "heavy_job_busy"}
                self._persist_cycle_summary(skipped)
                self._record_liveness(skipped)
                if reschedule and self._is_registered():
                    schedule_in_seconds(JOB_ID, self._tick, min(120, self.refresh_minutes * 60))
                return skipped
        # ponytail: release gate before ~127×2 scoring — holding it wedged resolver for hours
        return self._tick_body(reschedule=reschedule)

    def _complete_write_future(self, fut: Any, reschedule: bool) -> None:
        global _TICK_ACTIVE, _write_future
        try:
            try:
                result = dict(fut.result())
            except Exception as exc:
                result = {"ok": False, "error": str(exc)}
            result["run_at"] = _now_iso()
            with _lock:
                self._last_tick_at = result["run_at"]
                self._last_error = result.get("error")
                self._last_result = {
                    k: result.get(k) for k in ("count", "written_at", "path") if k in result
                }
            self._record_liveness(result)
            self._persist_cycle_summary(result)
            if result.get("ok"):
                logger.info(
                    "score snapshot cycle ok (deferred) count=%s path=%s",
                    result.get("count"),
                    result.get("path"),
                )
            else:
                logger.warning(
                    "score snapshot cycle failed (deferred): %s", result.get("error")
                )
        finally:
            with _lock:
                if _write_future is fut:
                    _write_future = None
                _TICK_ACTIVE = False
                self._tick_active = False
            # Deferred path: re-arm even when this tick was run_once/revive
            # (reschedule=False). Sync-complete and occupancy-skip keep the gate.
            if self._is_registered():
                schedule_in_seconds(JOB_ID, self._tick, self.refresh_minutes * 60)

    def _register_write_completion_callback(self, reschedule: bool) -> None:
        global _TICK_ACTIVE
        with _lock:
            fut = _write_future
        if fut is None:
            # Race: write finished and released between occupancy check and here.
            with _lock:
                _TICK_ACTIVE = False
                self._tick_active = False
            if self._is_registered():
                schedule_in_seconds(JOB_ID, self._tick, self.refresh_minutes * 60)
            return
        if fut.done():
            self._complete_write_future(fut, reschedule)
            return

        def _on_done(done_fut: Any) -> None:
            self._complete_write_future(done_fut, reschedule)

        fut.add_done_callback(_on_done)

    def _tick_body(self, reschedule: bool = True) -> Dict[str, Any]:
        global _TICK_ACTIVE
        with _lock:
            if _TICK_ACTIVE or _write_future_active():
                skipped = {
                    "ok": False,
                    "run_at": _now_iso(),
                    "skipped": "scoring_in_progress",
                }
                self._record_liveness(skipped)
                if reschedule and self._is_registered():
                    schedule_in_seconds(
                        JOB_ID, self._tick, min(120, self.refresh_minutes * 60)
                    )
                return skipped
            _TICK_ACTIVE = True
            self._tick_active = True
        try:
            self._clear_stuck_scoring()
            started_at = _now_iso()
            self._persist_cycle_summary({"run_at": started_at, "ok": False, "phase": "scoring"})

            def _progress(done: int, total: int) -> None:
                self._persist_cycle_summary(
                    {
                        "run_at": _now_iso(),
                        "ok": False,
                        "phase": "scoring",
                        "progress": f"{done}/{total}",
                    }
                )

            logger.info("score snapshot cycle started")
            try:
                result = write_full_universe_snapshot(progress_cb=_progress)
            except Exception as exc:
                logger.warning("score snapshot cycle exception: %s", exc)
                result = {"ok": False, "error": str(exc)}
            result["run_at"] = _now_iso()
            with _lock:
                self._last_tick_at = result["run_at"]
                self._last_error = result.get("error")
                self._last_result = {
                    k: result.get(k) for k in ("count", "written_at", "path") if k in result
                }
            self._record_liveness(result)
            self._persist_cycle_summary(result)
            if result.get("ok"):
                logger.info(
                    "score snapshot cycle ok count=%s path=%s",
                    result.get("count"),
                    result.get("path"),
                )
            else:
                logger.warning("score snapshot cycle failed: %s", result.get("error"))
            return result
        finally:
            if _scoring_write_in_progress():
                self._register_write_completion_callback(reschedule)
            else:
                with _lock:
                    _TICK_ACTIVE = False
                    self._tick_active = False
                if reschedule and self._is_registered():
                    schedule_in_seconds(JOB_ID, self._tick, self.refresh_minutes * 60)

    def _persist_cycle_summary(self, result: Dict[str, Any]) -> None:
        summary = {
            "run_at": result.get("run_at"),
            "ok": bool(result.get("ok")),
            "published": result.get("published"),
            "complete": result.get("complete"),
            "count": result.get("count"),
            "written_at": result.get("written_at"),
            "path": result.get("path"),
            "error": result.get("error"),
            "skipped": result.get("skipped"),
            "phase": result.get("phase"),
            "progress": result.get("progress"),
        }
        coverage = result.get("coverage")
        if isinstance(coverage, dict):
            from internal.council.snapshot_coverage import coverage_counts_summary

            summary["coverage"] = coverage_counts_summary(coverage)
        try:
            from internal.council import weights

            path = weights.SOUL_MAP_PATH
            data = weights._load_raw(path)
            sched = data.setdefault("score_snapshot_scheduler", {})
            if isinstance(sched, dict):
                sched["last_cycle"] = summary
                weights._save_raw(data, path)
        except Exception as exc:
            logger.warning("score snapshot cycle summary persist failed: %s", exc)


def _enabled() -> bool:
    return os.environ.get("SCORE_SNAPSHOT_SCHEDULER_ENABLED", "on").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


def start_score_snapshot_scheduler(immediate: bool = False) -> Dict[str, Any]:
    if not _enabled():
        return {"started": False, "reason": "disabled"}
    global _scheduler
    with _lock:
        if _scheduler is None:
            _scheduler = ScoreSnapshotScheduler()
    return _scheduler.start(immediate=immediate)


def stop_score_snapshot_scheduler() -> Dict[str, Any]:
    global _scheduler
    with _lock:
        sched = _scheduler
        _scheduler = None
    if sched is None:
        return {"stopped": False, "reason": "not running"}
    return sched.stop()


def _stopped_scheduler_state() -> Dict[str, Any]:
    snap: Dict[str, Any] = {}
    try:
        from internal.liveness import get_tracker

        t = get_tracker("score_snapshot")
        if t is not None:
            snap = t.snapshot()
    except Exception:
        pass
    return {
        "running": False,
        "refresh_minutes": SCORE_SNAPSHOT_REFRESH_MINUTES,
        "last_run_at": None,
        "last_run_error": None,
        "last_result": {},
        "age_seconds": snapshot_age_seconds(),
        "liveness": snap,
    }


def ensure_complete_snapshot() -> Dict[str, Any]:
    if _read_complete_snapshot() is not None:
        return {"ensured": False, "reason": "complete_snapshot_present"}
    return {"ensured": True, **revive_score_snapshot_scheduler()}


def get_score_snapshot_scheduler_state() -> Dict[str, Any]:
    """In-process state; web workers see soul_map via loop_health cross-process merge."""
    with _lock:
        if _scheduler is None:
            return {**_stopped_scheduler_state(), "enabled": _enabled()}
        return {**_scheduler.state(), "enabled": _enabled()}


def revive_score_snapshot_scheduler() -> Dict[str, Any]:
    """Best-effort in-place revive when ``score_snapshots.json`` goes stale.

    Loop stall guard strike 1 calls this. Idempotent ``start_*`` alone cannot
    refresh the artifact when the scheduler claims ``running`` but periodic
    ticks stopped (alive-but-hung). Recycle whenever ``_running`` (stop +
    cancel JOB_ID + start), then run one synchronous ``run_once`` so the
    guarded mtime actually moves.

    Blocks on the guard thread for up to ``SCORE_SNAPSHOT_WRITE_TIMEOUT_SECONDS``
    (default 600s) while ``run_once`` completes — not fire-and-forget.

    ponytail: ``stop``/``cancel_job`` cannot kill a hung Python thread; if
    module ``_TICK_ACTIVE`` or instance ``_tick_active`` is set, return
    ``tick_in_progress`` and let the in-flight body finish or hit the write
    timeout.
    """
    if not _enabled():
        return {"revived": False, "reason": "disabled"}

    age_before = snapshot_age_seconds()
    recycled = False
    with _lock:
        sched = _scheduler
        live = sched.liveness.snapshot() if sched else {}
        status_indicates_running = live.get("status") in {
            "failing",
            "stale",
            "starved",
        }
        running = bool(
            sched
            and live.get("lifecycle") != "new"
            and (
                live.get("lifecycle") == "started"
                or status_indicates_running
            )
        )
        tick_in_progress = (
            _write_future_active()
            or _TICK_ACTIVE
            or bool(sched and sched._tick_active)
        )

    if tick_in_progress:
        return {
            "revived": False,
            "reason": "tick_in_progress",
            "recycled": False,
            "age_before": age_before,
            "age_after": snapshot_age_seconds(),
        }

    if running:
        stop_score_snapshot_scheduler()
        recycled = True

    start_out = start_score_snapshot_scheduler(immediate=False)
    tick_out: Dict[str, Any] = {"ok": False, "error": "no_scheduler"}
    with _lock:
        sched = _scheduler
    if sched is not None:
        tick_out = sched.run_once()

    age_after = snapshot_age_seconds()
    revived = bool(
        tick_out.get("ok")
        and not tick_out.get("skipped")
        and age_after is not None
        and (
            (age_before is None and age_after < 60)
            or (age_before is not None and age_after < age_before)
        )
    )
    return {
        "revived": revived,
        "recycled": recycled,
        "age_before": age_before,
        "age_after": age_after,
        "start": start_out,
        "tick": tick_out,
    }
