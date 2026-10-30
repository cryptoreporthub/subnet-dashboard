"""Full-universe score snapshots off the request path (Learning Loop Phase 2).

Background job scores all tradable subnets and writes ``data/score_snapshots.json``.
Request handlers must never call full-universe scoring — they read this file
(or fall back to the existing volume/emission cap).
"""

from __future__ import annotations

import copy
import fcntl
import json
import logging
import os
import re
import time
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple

from internal.council.scorer_identity import (
    compute_input_digest,
    current_scorer_digest,
    current_weights_digest,
    finite_number,
    scorer_fields_match,
    stamp_scorer_fields,
)

from internal import build_cost
from internal.chain_read import ChainRead
from internal.council.scheduler_cycle_state import liveness_state_path as _liveness_state_path
from internal.council.snapshot_coverage import env_int, membership_allows_admission, membership_generation
from internal.job_scheduler import cancel_job, schedule_in_seconds
from internal.liveness import LivenessTracker

logger = logging.getLogger(__name__)

SCORE_SNAPSHOTS_PATH = os.environ.get(
    "SCORE_SNAPSHOTS_PATH", os.path.join("data", "score_snapshots.json")
)
SCORE_SNAPSHOT_SEED_PATH = os.environ.get(
    "SCORE_SNAPSHOT_SEED_PATH", os.path.join("data_seeds", "score_snapshots.json")
)


def _score_snapshot_cycle_path() -> str:
    override = os.environ.get("SCORE_SNAPSHOT_CYCLE_PATH")
    if override:
        return override
    return os.path.join(os.path.dirname(SCORE_SNAPSHOTS_PATH) or ".", "score_snapshot_cycle.json")


_served_parse_cache: Dict[Tuple[str, int, int], Dict[str, Any]] = {}
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
# JOB_ID is one process-wide APScheduler slot shared by every scheduler
# generation. _job_lock makes "check still current + (re)schedule" and
# "cancel only my own job" atomic; _job_owner is the generation that last
# scheduled it. Lock order: _job_lock before _lock, never the reverse.
_job_lock = threading.Lock()
_job_owner: Optional["ScoreSnapshotScheduler"] = None
# Every scheduler generation persists the same score_snapshot liveness record
# (LivenessTracker saves its whole in-memory state), so a generation that is no
# longer the registered one must never write it. ScoreSnapshotScheduler._persist_liveness
# is the only path to a liveness write: it checks ownership and writes together
# under _lifecycle_lock, and registering a replacement (which loads the persisted
# record) takes the same lock. Lock order: _lifecycle_lock, _job_lock, _lock.
_lifecycle_lock = threading.Lock()


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
    """Age of whatever the volume file holds; None when it is absent or unreadable.

    This is the volume's freshness, so a seed is never consulted: while the volume is absent or
    holds something incomplete, readers are served the (much older) seed, and reporting the seed's
    age here made a stale or missing volume look like the seed's age. Callers: the revive check
    (did a tick refresh the volume?), ops probes (``loop_health``, which falls back to the file's
    mtime and then the last tick when this is None) and the scheduler state. Pick readers and the
    ``subnet_score_snapshot_age_seconds`` gauge want the age of what is *served* and use
    ``read_served_snapshot(...).age_seconds`` instead.
    """
    volume_path = path or SCORE_SNAPSHOTS_PATH
    snap = load_score_snapshot(volume_path)
    if snap is None:
        return None
    return _snapshot_age_for_path(volume_path, snap)


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
            except BlockingIOError:  # another process holds the lock; any other OSError is a real failure
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
        st = os.stat(snap_path)
        key = (snap_path, st.st_mtime_ns, st.st_size)
        cached = _served_parse_cache.get(key)
        if cached is not None:
            return copy.deepcopy(cached)
        with open(snap_path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        if not isinstance(data, dict):
            return None
        _served_parse_cache.clear()
        _served_parse_cache[key] = data
        return copy.deepcopy(data)
    except Exception:
        return None


def _row_ids(rows: Any) -> Optional[List[int]]:
    if not isinstance(rows, list):
        return None
    ids: List[int] = []
    for row in rows:
        if not isinstance(row, dict):
            return None
        netuid = row.get("netuid")
        if type(netuid) is not int or netuid <= 0:
            return None
        # The producer writes ``total_score = float(score or 0)`` on every row it emits, so a row with no
        # finite numeric score is not a scored row and must not count towards "every netuid was scored".
        score = row.get("total_score")
        if not finite_number(score):
            return None
        ids.append(netuid)
    return ids


# Both digests are sha256 hexdigests (scorer_identity._canonical_digest). Readers cannot recompute them:
# weights_digest depends on the live soul_map (the producer gate compares it) and input_digest on the
# scored feed rows and market weights, which are not persisted. A reader can still refuse anything that
# is not shaped like the digest the producer writes.
_SHA256_HEX = re.compile(r"[0-9a-f]{64}")


def _provenance_matches(provenance: Any, membership: Dict[str, Any], chain: ChainRead) -> bool:
    """The snapshot's own provenance must agree with its embedded receipt and chain read."""
    if not isinstance(provenance, dict):
        return False
    generation = membership_generation(chain.netuids)
    if membership.get("generation") != generation or provenance.get("membership_generation") != generation:
        return False
    if provenance.get("membership_block_hash") != chain.block_hash or provenance.get("membership_rpc") != chain.rpc:
        return False
    return all(
        isinstance(provenance.get(key), str) and _SHA256_HEX.fullmatch(provenance[key])
        for key in ("weights_digest", "input_digest")
    )


def is_complete_snapshot(snap: Any) -> bool:
    """Single domain predicate for publish and serve (#1479). Total: never raises."""
    if not isinstance(snap, dict):
        return False
    coverage = snap.get("coverage")
    if not isinstance(coverage, dict) or coverage.get("complete") is not True:
        return False
    if not scorer_fields_match(snap):
        return False
    membership = coverage.get("membership")
    chain = ChainRead.parse(membership.get("chain")) if isinstance(membership, dict) else None
    if chain is None:
        return False
    # The pinned chain read is the only membership truth: every other field must agree with it,
    # including the receipt's own top-level copy of the block and provider.
    if membership.get("block_hash") != chain.block_hash or membership.get("rpc") != chain.rpc:
        return False
    expected = list(chain.netuids)
    listed = membership.get("expected_netuids")
    if not isinstance(listed, list) or any(type(n) is not int for n in listed) or sorted(listed) != expected:
        return False
    if membership.get("fresh") is not True or not membership_allows_admission(membership):
        return False
    for horizon in ("day", "hour"):
        block = coverage.get(horizon)
        if not isinstance(block, dict) or block.get("complete") is not True:
            return False
        # A horizon that declares its expected list must declare exactly the chain read.
        declared = block.get("expected")
        if declared is not None and (
            not isinstance(declared, list)
            or any(type(n) is not int for n in declared)
            or sorted(declared) != expected
        ):
            return False
    if not _provenance_matches(snap.get("provenance"), membership, chain):
        return False
    day = _row_ids(snap.get("day"))
    if day is None or sorted(day) != expected:
        return False
    hour = _row_ids(snap.get("hour"))
    return hour is not None and sorted(hour) == expected


def _atomic_write_json(path: str, payload: Dict[str, Any]) -> None:
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    tmp = os.path.join(directory, f".{os.path.basename(path)}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        hook = os.environ.get("SCORE_SNAPSHOT_ATOMIC_TEST_HOOK")
        if hook == "sigkill_after_tmp_write":
            import signal

            os.kill(os.getpid(), signal.SIGKILL)
        os.replace(tmp, path)
        dir_fd = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        except OSError as exc:
            logger.debug("score snapshot dir fsync skipped: %s", exc)
        finally:
            os.close(dir_fd)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def publish_complete_snapshot(payload: Dict[str, Any], path: Optional[str] = None) -> Dict[str, Any]:
    """Publish only complete snapshots; atomic durable write."""
    snap_path = path or SCORE_SNAPSHOTS_PATH
    stamped = stamp_scorer_fields(payload)
    if not is_complete_snapshot(stamped):
        return {
            "published": False,
            "skipped_older": False,
            "refused": "incomplete",
            "timing": {"publish_wall_seconds": 0.0},
        }
    os.makedirs(os.path.dirname(snap_path) or ".", exist_ok=True)
    with _locked_score_snapshot(snap_path):
        publish_started = time.monotonic()
        current = load_score_snapshot(snap_path)
        incoming = _snapshot_stamp(stamped)
        on_disk = _snapshot_stamp(current) if is_complete_snapshot(current or {}) else None
        if incoming is not None and on_disk is not None and incoming < on_disk:
            logger.info(
                "score snapshot publish skipped: incoming %s is older than on-disk %s",
                stamped.get("build_started_at") or stamped.get("written_at"),
                (current or {}).get("build_started_at") or (current or {}).get("written_at"),
            )
            publish_wall = time.monotonic() - publish_started
            return {
                "published": False,
                "skipped_older": True,
                "timing": {"publish_wall_seconds": round(publish_wall, 6)},
            }
        _atomic_write_json(snap_path, stamped)
        _served_parse_cache.clear()
        publish_wall = time.monotonic() - publish_started
        return {
            "published": True,
            "skipped_older": False,
            "timing": {"publish_wall_seconds": round(publish_wall, 6)},
        }


def record_cycle_receipt(
    coverage: Dict[str, Any],
    *,
    outcome: str,
    path: Optional[str] = None,
) -> None:
    """Per-cycle producer receipt — never served to pick readers."""
    cycle_path = path or _score_snapshot_cycle_path()
    day_block = coverage.get("day") if isinstance(coverage.get("day"), dict) else {}
    receipt = {
        "attempted_at": _now_iso(),
        "outcome": outcome,
        "complete": bool(coverage.get("complete")),
        "capture_reason": coverage.get("capture_reason"),
        "membership_admission_allowed": coverage.get("membership_admission_allowed"),
        "membership_admission_gate_reason": coverage.get("membership_admission_gate_reason"),
        "day": {
            "expected": day_block.get("expected_count"),
            "succeeded": day_block.get("succeeded_count"),
            "failed": day_block.get("failed_count"),
        },
    }
    try:
        _atomic_write_json(cycle_path, receipt)
    except Exception as exc:
        logger.warning("score snapshot cycle receipt write failed: %s", exc)


def producer_cycle_age_seconds(path: Optional[str] = None) -> Optional[float]:
    cycle_path = path or _score_snapshot_cycle_path()
    try:
        with open(cycle_path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    parsed = _parse_iso(data.get("attempted_at"))
    if parsed is None:
        return None
    return max(0.0, datetime.now(timezone.utc).timestamp() - parsed.timestamp())


def snapshot_membership_current(snap: Optional[Dict[str, Any]]) -> Optional[bool]:
    """Does the snapshot's scored set still match the live membership? None when that cannot be said.

    Readers only label this; refusing a moved snapshot would blank picks on the first deregistration.
    """
    if not snap:
        return None
    from internal.council.snapshot_coverage import (
        load_membership_receipt,
        membership_allows_admission,
        membership_generation,
    )

    receipt = load_membership_receipt()
    if not membership_allows_admission(receipt):
        return None
    membership = ((snap.get("coverage") or {}).get("membership")) or {}
    return receipt.get("generation") == membership_generation(membership.get("expected_netuids") or [])


class ServedState(str, Enum):
    FRESH = "fresh"
    AGED = "aged"
    SEED = "seed"
    NONE = "none"


@dataclass(frozen=True)
class ServedSnapshot:
    state: ServedState
    snapshot: Optional[Dict[str, Any]]
    age_seconds: Optional[float]
    origin: Optional[str]
    reason: Optional[str]

    @property
    def servable(self) -> bool:
        return self.state is not ServedState.NONE

    def label(self, *, max_age_seconds: Optional[int] = None) -> Dict[str, Any]:
        ttl = SCORE_SNAPSHOT_MAX_AGE_SECONDS if max_age_seconds is None else max_age_seconds
        membership_current = snapshot_membership_current(self.snapshot)
        stale_alert = self.state in (ServedState.AGED, ServedState.SEED)
        if self.state is ServedState.FRESH and self.age_seconds is not None and ttl > 0:
            stale_alert = self.age_seconds > ttl
        if self.state is ServedState.SEED or membership_current is False:
            stale_alert = True
        out: Dict[str, Any] = {
            "snapshot_state": self.state.value,
            "snapshot_origin": self.origin,
            "snapshot_age_seconds": round(self.age_seconds, 3) if self.age_seconds is not None else None,
            "stale_alert": stale_alert,
            "membership_current": membership_current,
        }
        if self.reason:
            out["reason"] = self.reason
        return out


def _snapshot_age_for_path(path: str, snap: Optional[Dict[str, Any]]) -> Optional[float]:
    started = _parse_iso((snap or {}).get("build_started_at")) if snap else None
    if started is not None:
        return max(0.0, datetime.now(timezone.utc).timestamp() - started.timestamp())
    try:
        return max(0.0, datetime.now(timezone.utc).timestamp() - os.path.getmtime(path))
    except OSError:
        return None


def read_served_snapshot(
    path: Optional[str] = None,
    seed_path: Optional[str] = None,
    max_age_seconds: Optional[int] = None,
) -> ServedSnapshot:
    """Newest complete snapshot from volume, else compatible seed; never serves partials."""
    ttl = SCORE_SNAPSHOT_MAX_AGE_SECONDS if max_age_seconds is None else max_age_seconds
    volume_path = path or SCORE_SNAPSHOTS_PATH
    seed = seed_path or SCORE_SNAPSHOT_SEED_PATH

    def _classify(
        snap: Dict[str, Any],
        origin: str,
        snap_path: str,
        *,
        seed_origin: bool,
        seed_reason: Optional[str] = None,
    ) -> ServedSnapshot:
        age = _snapshot_age_for_path(snap_path, snap)
        if seed_origin:
            return ServedSnapshot(ServedState.SEED, snap, age, "seed", seed_reason)
        if age is not None and ttl > 0 and age <= ttl:
            return ServedSnapshot(ServedState.FRESH, snap, age, origin, None)
        return ServedSnapshot(ServedState.AGED, snap, age, origin, None)

    volume_snap = load_score_snapshot(volume_path)
    if volume_snap and is_complete_snapshot(volume_snap):
        return _classify(volume_snap, "volume", volume_path, seed_origin=False)

    seed_snap = load_score_snapshot(seed)
    if seed_snap and is_complete_snapshot(seed_snap):
        reason = "volume_not_complete" if volume_snap else "volume_missing"
        return _classify(seed_snap, "seed", seed, seed_origin=True, seed_reason=reason)

    if volume_snap and not is_complete_snapshot(volume_snap):
        return ServedSnapshot(ServedState.NONE, None, None, None, "volume_not_complete")
    return ServedSnapshot(ServedState.NONE, None, None, None, "seed_unavailable")


def volume_has_fresh_complete_snapshot(
    path: Optional[str] = None,
    max_age_seconds: Optional[int] = None,
) -> bool:
    """Producer gate: fresh complete on volume only — seed/aged do not block ensure."""
    volume_path = path or SCORE_SNAPSHOTS_PATH
    snap = load_score_snapshot(volume_path)
    if not snap or not is_complete_snapshot(snap):
        return False
    ttl = SCORE_SNAPSHOT_MAX_AGE_SECONDS if max_age_seconds is None else max_age_seconds
    age = _snapshot_age_for_path(volume_path, snap)
    if age is None:
        return False
    if ttl > 0 and age > ttl:
        return False
    # Readers keep serving a moved snapshot; only the producer must rebuild it.
    if snapshot_membership_current(snap) is False:
        return False
    # is_complete_snapshot above guarantees a dict provenance with a digest-shaped weights_digest.
    # An unreadable soul_map gives None (unknown weights, not default weights): never equal to a stamp.
    return snap["provenance"]["weights_digest"] == current_weights_digest()


def _served_snapshot_tuple(
    path: Optional[str] = None,
    max_age_seconds: Optional[int] = None,
) -> Optional[Tuple[Dict[str, Any], float, ServedSnapshot]]:
    served = read_served_snapshot(path=path, max_age_seconds=max_age_seconds)
    if not served.servable or served.snapshot is None:
        return None
    age = served.age_seconds if served.age_seconds is not None else 0.0
    return served.snapshot, age, served


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
    """Return subnets sorted by snapshot score, or None if no complete snapshot is servable."""
    got = _served_snapshot_tuple(path, max_age_seconds)
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
    got = _served_snapshot_tuple(path, max_age_seconds)
    if got is None:
        return None
    snap, age, served = got
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
            **served.label(max_age_seconds=max_age_seconds),
        },
    }


def day_scored_from_snapshot(
    subnets: List[Dict[str, Any]],
    *,
    max_age_seconds: Optional[int] = None,
    path: Optional[str] = None,
) -> Optional[List[Dict[str, Any]]]:
    """Join tradable subnets to day scores from snapshot (minimal score payloads)."""
    got = _served_snapshot_tuple(path, max_age_seconds)
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
                    "expert_contributions": dict(h.get("expert_contributions") or {}),
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
                "expert_contributions": dict(d.get("expert_contributions") or {}),
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


# Last observed soul_map state (None until the first build). Logging happens on change only, so a
# soul_map that stays missing costs one line, not one per cycle.
_weights_available: Optional[bool] = None
_weights_state_lock = threading.Lock()


def _note_weights_availability(available: bool) -> None:
    global _weights_available
    with _weights_state_lock:
        previous, _weights_available = _weights_available, available
    if available and previous is False:
        logger.info("score snapshot build: weights available again, resuming builds")
    elif not available and previous is not False:
        logger.warning(
            "score snapshot build skipped: weights_unavailable (soul_map missing or unusable); "
            "the shipped seed is served until it is readable"
        )


def write_full_universe_snapshot(
    progress_cb: Optional[Callable[[int, int], None]] = None,
) -> Dict[str, Any]:
    """Load subnets, score, persist. Call only from background."""
    capture_started = time.monotonic()
    prep_meta: Dict[str, Any] = {}
    write_stage_timing: Dict[str, Any] = {}
    receipt: Dict[str, Any] = {}
    try:
        # Taken once, before anything is loaded: a weight edit during the build must show up as
        # "changed", not be absorbed. None means the soul_map is missing or unusable (weights unknown,
        # not defaults), so the build is skipped instead of scoring ~128 subnets that could never be
        # published. Inside the try so a read failure is a build error, as it was before.
        weights_digest = current_weights_digest()
        _note_weights_availability(weights_digest is not None)
        if weights_digest is None:
            skipped = {"complete": False, "capture_reason": "weights_unavailable"}
            record_cycle_receipt(skipped, outcome="skipped")
            return {
                "ok": False,
                "published": False,
                "skipped_older": False,
                "complete": False,
                "skipped": "weights_unavailable",
                "coverage": skipped,
            }
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
        record_cycle_receipt(
            {"complete": False, "capture_reason": "subnet_load_error"},
            outcome="error",
        )
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
        coverage: Dict[str, Any] = {"complete": False}
        build_started = time.monotonic()
        build_cost.begin(build_id)
        try:
            payload = build_full_universe_snapshot(
                subnets or [],
                ctx,
                progress_cb=progress_cb,
            )
        except Exception as exc:
            record_cycle_receipt(
                {"complete": False, "capture_reason": "build_raise", "build_error": str(exc)},
                outcome="error",
            )
            raise
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
        candidate = stamp_scorer_fields({**payload, "source": source, "coverage": coverage})
        if not coverage.get("complete"):
            coverage["published"] = False
            publish_result = {
                "published": False,
                "skipped_older": False,
                "refused": "incomplete",
                "timing": {"publish_wall_seconds": 0.0},
            }
        else:
            candidate["build_provenance"] = {
                "source": "write_full_universe_snapshot",
                "build_id": build_id,
                "day_expected_count": len(expected),
                "day_succeeded_count": len(list(inputs.get("day_succeeded") or [])),
            }
            candidate["provenance"] = {
                "membership_generation": receipt.get("generation"),
                "membership_block_hash": receipt.get("block_hash"),
                "membership_rpc": receipt.get("rpc"),
                "membership_resolved_at": receipt.get("resolved_at"),
                "weights_digest": weights_digest,
                "input_digest": compute_input_digest(
                    str(receipt.get("generation")),
                    current_scorer_digest(),
                    list(inputs.get("tradable_rows") or []),
                    ctx.get("weights") or {},
                ),
            }
            publish_result = publish_complete_snapshot(candidate)
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
        outcome = "published" if published else ("skipped_older" if skipped_older else "incomplete")
        note_cycle(coverage)
        record_cycle_receipt(coverage, outcome=outcome)
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
        self._armed = False
        self._last_tick_at: Optional[str] = None
        self._last_error: Optional[str] = None
        self._last_result: Dict[str, Any] = {}
        self.liveness = LivenessTracker(
            name="score_snapshot",
            interval_seconds=max(60, self.refresh_minutes * 60),
            staleness_factor=2,
            persist=True,
            # Its own file: a tick must never create or rewrite the soul_map the weights gate reads.
            persist_path=_liveness_state_path,
        )

    def _is_registered(self) -> bool:
        with _lock:
            return _scheduler is self

    def _arm_still_valid(self) -> bool:
        with _lock:
            return _scheduler is self and self._armed

    def _stopped_during_arm(self) -> Optional[Dict[str, Any]]:
        """Fence deferred/immediate arm against concurrent stop/unregister."""
        if self._arm_still_valid():
            return None
        return {"started": False, "reason": "stopped_during_arm"}

    def _schedule_tick(self, seconds: float) -> bool:
        """(Re)schedule JOB_ID for this generation; refuse once it is stopped."""
        global _job_owner
        with _job_lock:
            if not self._arm_still_valid():
                return False
            schedule_in_seconds(JOB_ID, self._scheduled_tick, seconds)
            _job_owner = self
            return True

    def _cancel_own_job(self) -> None:
        """Disarm and cancel JOB_ID unless a replacement generation owns it.

        _armed is cleared under _lock while _job_lock is still held, so a tick
        that already passed _arm_still_valid() cannot reschedule after failed startup.
        """
        global _job_owner
        with _job_lock:
            with _lock:
                self._armed = False
            if _job_owner is self:
                _job_owner = None
                cancel_job(JOB_ID)

    def _persist_liveness(self, write: Callable[[LivenessTracker], None], *, strict: bool = False) -> bool:
        """The only way this scheduler writes the shared liveness record.

        Ownership check and write are atomic under _lifecycle_lock. A replaced
        generation is fenced out (returns False). ``strict`` (startup) also
        requires the registered generation to be armed; the others accept an
        unregistered module (clean shutdown, a tick finishing after stop()).
        """
        with _lifecycle_lock:
            with _lock:
                current = _scheduler is self
                if not current and not strict:
                    current = _scheduler is None
                if strict:
                    current = current and self._armed
            if not current:
                return False
            write(self.liveness)
            return True

    def _start_liveness(self) -> bool:
        return self._persist_liveness(lambda t: t.start(), strict=True)

    def _stop_liveness_if_current(self) -> bool:
        """Persist 'stopped' unless a replacement generation is registered."""
        return self._persist_liveness(lambda t: t.stop())

    def _scheduled_tick(self) -> Dict[str, Any]:
        """Entry point for scheduled and thread-dispatched ticks."""
        return self._tick(gate_on_arm=True)

    def start(self, immediate: bool = False) -> Dict[str, Any]:
        if not self._is_registered():
            return {"started": False, "reason": "not registered"}
        with _lock:
            if self._armed:
                return {"started": False, "reason": "already_armed"}
            self._armed = True
        try:
            resumed_lifecycle = self.liveness.snapshot().get("lifecycle") == "started"
            armed = "immediate" if immediate else "deferred"
            if immediate:
                # A started tick thread cannot be cancelled; a liveness
                # failure must abort before the thread exists. Deferred mode
                # stays schedule-first so a failed schedule leaves the
                # lifecycle unchanged (_cancel_own_job covers that path).
                self._start_liveness()
                try:
                    threading.Thread(
                        target=self._scheduled_tick,
                        daemon=True,
                        name="score-snap-tick",
                    ).start()
                except Exception:
                    self._stop_liveness_if_current()
                    raise
            elif not self._schedule_tick(SCORE_SNAPSHOT_FIRST_DELAY_SECONDS):
                return {"started": False, "reason": "stopped_during_arm"}
            else:
                self._start_liveness()
            aborted = self._stopped_during_arm()
            if aborted:
                # Unregistered without stop(): drop our pending job and disarm.
                self._cancel_own_job()
                self._stop_liveness_if_current()
                return aborted
        except Exception:
            self._cancel_own_job()
            raise
        return {
            "started": True,
            "armed": armed,
            "resumed_lifecycle": resumed_lifecycle,
            "refresh_minutes": self.refresh_minutes,
        }

    def stop(self) -> Dict[str, Any]:
        with _lock:
            self._armed = False
        self._cancel_own_job()
        self._stop_liveness_if_current()
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
            from internal.council.scheduler_cycle_state import read_last_cycle

            last = read_last_cycle()
            if last.get("phase") != "scoring":
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
            from internal.council.scheduler_cycle_state import read_last_cycle

            last = read_last_cycle()
            if last.get("phase") != "scoring":
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
        self._persist_liveness(lambda t: self._write_liveness_result(t, result))

    def _write_liveness_result(self, tracker: LivenessTracker, result: Dict[str, Any]) -> None:
        skipped = result.get("skipped")
        if skipped:
            tracker.record_skip(str(skipped))
            return
        if result.get("skipped_older"):
            tracker.record_skip("skipped_older")
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
            tracker.record_success(evidence=evidence)
            return
        tracker.record_failure(
            error=str(result.get("error") or "score_snapshot_unpublished")
        )

    def _tick(self, reschedule: bool = True, *, gate_on_arm: bool = False) -> Dict[str, Any]:
        from internal.heavy_job_gate import heavy_job_slot

        if gate_on_arm and not self._arm_still_valid():
            return {"ok": False, "run_at": _now_iso(), "skipped": "stopped_during_arm"}

        if self._scoring_in_progress():
            skipped = {"ok": False, "run_at": _now_iso(), "skipped": "scoring_in_progress"}
            # ponytail: skip persist while body runs — would drop phase=scoring and hide in-flight work
            if not self._tick_active:
                self._persist_cycle_summary(skipped)
                self._record_liveness(skipped)
            if reschedule:
                self._schedule_tick(min(120, self.refresh_minutes * 60))
            return skipped

        with heavy_job_slot("score_snapshot") as acquired:
            if not acquired:
                skipped = {"ok": False, "run_at": _now_iso(), "skipped": "heavy_job_busy"}
                self._persist_cycle_summary(skipped)
                self._record_liveness(skipped)
                if reschedule:
                    self._schedule_tick(min(120, self.refresh_minutes * 60))
                return skipped
        # ponytail: release gate before ~127×2 scoring — holding it wedged resolver for hours
        return self._tick_body(reschedule=reschedule, gate_on_arm=gate_on_arm)

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
            self._schedule_tick(self.refresh_minutes * 60)

    def _register_write_completion_callback(self, reschedule: bool) -> None:
        global _TICK_ACTIVE
        with _lock:
            fut = _write_future
        if fut is None:
            # Race: write finished and released between occupancy check and here.
            with _lock:
                _TICK_ACTIVE = False
                self._tick_active = False
            self._schedule_tick(self.refresh_minutes * 60)
            return
        if fut.done():
            self._complete_write_future(fut, reschedule)
            return

        def _on_done(done_fut: Any) -> None:
            self._complete_write_future(done_fut, reschedule)

        fut.add_done_callback(_on_done)

    def _tick_body(
        self, reschedule: bool = True, *, gate_on_arm: bool = False
    ) -> Dict[str, Any]:
        global _TICK_ACTIVE
        with _lock:
            # Admission and stop() are linearized on _lock: a gated tick either
            # claims the active slot before stop, or sees the stop and bails.
            if gate_on_arm and not (_scheduler is self and self._armed):
                return {"ok": False, "run_at": _now_iso(), "skipped": "stopped_during_arm"}
            busy = _TICK_ACTIVE or _write_future_active()
            if not busy:
                _TICK_ACTIVE = True
                self._tick_active = True
        if busy:
            skipped = {
                "ok": False,
                "run_at": _now_iso(),
                "skipped": "scoring_in_progress",
            }
            self._record_liveness(skipped)
            if reschedule:
                self._schedule_tick(min(120, self.refresh_minutes * 60))
            return skipped
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
                if reschedule:
                    self._schedule_tick(self.refresh_minutes * 60)

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
        # Never the soul_map: a tick must not create or rewrite the file the weights gate reads.
        from internal.council.scheduler_cycle_state import write_last_cycle

        write_last_cycle(summary)


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
    from internal.run_mode import score_snapshot_producer_enabled

    if not score_snapshot_producer_enabled():
        return {"started": False, "reason": "not_owner"}
    global _scheduler
    # Constructing a scheduler loads the persisted liveness record; do it under
    # _lifecycle_lock so no outgoing generation can write between load and register.
    with _lifecycle_lock:
        with _lock:
            if _scheduler is None:
                _scheduler = ScoreSnapshotScheduler()
            sched = _scheduler
    return sched.start(immediate=immediate)


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
    from internal.run_mode import score_snapshot_producer_enabled

    if not score_snapshot_producer_enabled():
        return {"revived": False, "reason": "not_owner"}

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
