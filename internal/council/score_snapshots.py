"""Full-universe score snapshots off the request path (Learning Loop Phase 2).

Background job scores all tradable subnets and writes ``data/score_snapshots.json``.
Request handlers must never call full-universe scoring — they read this file
(or fall back to the existing volume/emission cap).
"""

from __future__ import annotations

import json
import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

from internal.job_scheduler import cancel_job, schedule_in_seconds

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
SCORE_SNAPSHOT_MAX_SUBNETS = int(os.environ.get("SCORE_SNAPSHOT_MAX_SUBNETS", "0"))
JOB_ID = "score-snapshot-scheduler"

_lock = threading.Lock()
_scheduler: Optional["ScoreSnapshotScheduler"] = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_iso(value: Any) -> Optional[datetime]:
    if not value or not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def snapshot_age_seconds(path: Optional[str] = None) -> Optional[float]:
    snap_path = path or SCORE_SNAPSHOTS_PATH
    try:
        return max(0.0, datetime.now(timezone.utc).timestamp() - os.path.getmtime(snap_path))
    except OSError:
        return None


def load_score_snapshot(path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    snap_path = path or SCORE_SNAPSHOTS_PATH
    try:
        with open(snap_path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def save_score_snapshot(payload: Dict[str, Any], path: Optional[str] = None) -> None:
    snap_path = path or SCORE_SNAPSHOTS_PATH
    os.makedirs(os.path.dirname(snap_path) or ".", exist_ok=True)
    tmp = snap_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
    os.replace(tmp, snap_path)


def day_scores_by_netuid(snapshot: Optional[Dict[str, Any]] = None) -> Dict[int, float]:
    snap = snapshot if snapshot is not None else load_score_snapshot()
    if not snap:
        return {}
    out: Dict[int, float] = {}
    for row in snap.get("day") or []:
        if not isinstance(row, dict):
            continue
        try:
            netuid = int(row.get("netuid"))
            out[netuid] = float(row.get("total_score") or 0)
        except (TypeError, ValueError):
            continue
    return out


def rank_subnets_by_snapshot(
    subnets: List[Dict[str, Any]],
    *,
    horizon: str = "day",
    max_age_seconds: Optional[int] = None,
    path: Optional[str] = None,
) -> Optional[List[Dict[str, Any]]]:
    """Return subnets sorted by snapshot score, or None if snapshot missing/stale."""
    age = snapshot_age_seconds(path)
    limit = SCORE_SNAPSHOT_MAX_AGE_SECONDS if max_age_seconds is None else max_age_seconds
    if age is None or age > limit:
        return None
    snap = load_score_snapshot(path)
    if not snap:
        return None
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
    market_context = market_context or {}
    rows = tradable_subnets(subnets) if subnets else []
    hour_rows: List[Dict[str, Any]] = []
    day_rows: List[Dict[str, Any]] = []
    total = len(rows)
    for idx, sn in enumerate(rows):
        try:
            netuid = int(sn.get("netuid"))
        except (TypeError, ValueError):
            continue
        if score_hour:
            try:
                h = score_subnet_for_hour(sn, market_context)
                hour_rows.append(
                    {
                        "netuid": netuid,
                        "total_score": float(h.get("total_score") or 0),
                        "name": sn.get("name"),
                    }
                )
            except Exception:
                pass
        try:
            d = score_subnet_for_day(sn, market_context)
            day_rows.append(
                {
                    "netuid": netuid,
                    "total_score": float(d.get("total_score") or 0),
                    "name": sn.get("name"),
                }
            )
        except Exception:
            pass
        if progress_cb and total and (idx + 1) % 20 == 0:
            progress_cb(idx + 1, total)

    if not score_hour and day_rows:
        hour_rows = [dict(row) for row in day_rows]

    hour_rows.sort(key=lambda r: r["total_score"], reverse=True)
    day_rows.sort(key=lambda r: r["total_score"], reverse=True)
    return {
        "written_at": _now_iso(),
        "count": len(rows),
        "hour": hour_rows,
        "day": day_rows,
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


def write_full_universe_snapshot(
    progress_cb: Optional[Callable[[int, int], None]] = None,
) -> Dict[str, Any]:
    """Load subnets, score, persist. Call only from background."""
    try:
        from server import _get_subnets_hydrate, _get_subnets_with_source, _market_context_with_weights

        if _registry_only_snapshot():
            subnets, source = _get_subnets_hydrate()
        else:
            subnets, source = _get_subnets_with_source(timeout=20)
            if not subnets:
                subnets, source = _get_subnets_hydrate()
        cap = SCORE_SNAPSHOT_MAX_SUBNETS
        if cap > 0 and subnets and len(subnets) > cap:
            from server import _cap_subnets_for_scoring

            subnets = _cap_subnets_for_scoring(subnets, limit=cap)
        ctx = _market_context_with_weights(subnets or [])
    except Exception as exc:
        return {"ok": False, "error": f"subnet load: {exc}"}

    def _build_and_save() -> Dict[str, Any]:
        payload = build_full_universe_snapshot(
            subnets or [],
            ctx,
            progress_cb=progress_cb,
        )
        payload["source"] = source
        save_score_snapshot(payload)
        return {
            "ok": True,
            "count": payload.get("count"),
            "written_at": payload.get("written_at"),
            "path": SCORE_SNAPSHOTS_PATH,
        }

    timeout = SCORE_SNAPSHOT_WRITE_TIMEOUT_SECONDS
    if timeout <= 0:
        try:
            return _build_and_save()
        except Exception as exc:
            logger.warning("score snapshot write failed: %s", exc)
            return {"ok": False, "error": str(exc)}

    pool = ThreadPoolExecutor(max_workers=1)
    try:
        fut = pool.submit(_build_and_save)
        try:
            return fut.result(timeout=timeout)
        except FuturesTimeoutError:
            logger.warning(
                "score snapshot write timed out after %ds", timeout
            )
            return {"ok": False, "error": f"write_timeout_{timeout}s"}
    except Exception as exc:
        logger.warning("score snapshot write failed: %s", exc)
        return {"ok": False, "error": str(exc)}
    finally:
        pool.shutdown(wait=False, cancel_futures=True)


class ScoreSnapshotScheduler:
    def __init__(self, refresh_minutes: int = SCORE_SNAPSHOT_REFRESH_MINUTES) -> None:
        self.refresh_minutes = max(10, min(int(refresh_minutes), 24 * 60))
        self._running = False
        self._last_run_at: Optional[str] = None
        self._last_ok: Optional[bool] = None
        self._last_error: Optional[str] = None
        self._last_result: Dict[str, Any] = {}

    def start(self, immediate: bool = False) -> Dict[str, Any]:
        with _lock:
            if self._running:
                return {"started": False, "reason": "already running"}
            self._running = True
        if immediate:
            threading.Thread(target=self._tick, daemon=True, name="score-snap-tick").start()
        else:
            # After pick schedulers; full score is the heavy job.
            schedule_in_seconds(JOB_ID, self._tick, SCORE_SNAPSHOT_FIRST_DELAY_SECONDS)
        return {"started": True, "refresh_minutes": self.refresh_minutes}

    def stop(self) -> Dict[str, Any]:
        with _lock:
            self._running = False
        cancel_job(JOB_ID)
        return {"stopped": True}

    def state(self) -> Dict[str, Any]:
        return {
            "running": self._running,
            "refresh_minutes": self.refresh_minutes,
            "last_run_at": self._last_run_at,
            "last_run_ok": self._last_ok,
            "last_run_error": self._last_error,
            "last_result": self._last_result,
            "age_seconds": snapshot_age_seconds(),
        }

    def run_once(self) -> Dict[str, Any]:
        return self._tick(reschedule=False)

    def _scoring_in_progress(self) -> bool:
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

    def _tick(self, reschedule: bool = True) -> Dict[str, Any]:
        from internal.heavy_job_gate import heavy_job_slot

        if self._scoring_in_progress():
            skipped = {"ok": True, "run_at": _now_iso(), "skipped": "scoring_in_progress"}
            self._persist_cycle_summary(skipped)
            if reschedule and self._running:
                schedule_in_seconds(JOB_ID, self._tick, min(120, self.refresh_minutes * 60))
            return skipped

        with heavy_job_slot("score_snapshot") as acquired:
            if not acquired:
                skipped = {"ok": True, "run_at": _now_iso(), "skipped": "heavy_job_busy"}
                self._persist_cycle_summary(skipped)
                if reschedule and self._running:
                    schedule_in_seconds(JOB_ID, self._tick, min(120, self.refresh_minutes * 60))
                return skipped
        # ponytail: release gate before ~127×2 scoring — holding it wedged resolver for hours
        return self._tick_body(reschedule=reschedule)

    def _tick_body(self, reschedule: bool = True) -> Dict[str, Any]:
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
            self._last_run_at = result["run_at"]
            self._last_ok = bool(result.get("ok"))
            self._last_error = result.get("error")
            self._last_result = {
                k: result.get(k) for k in ("count", "written_at", "path") if k in result
            }
        self._persist_cycle_summary(result)
        if result.get("ok"):
            logger.info(
                "score snapshot cycle ok count=%s path=%s",
                result.get("count"),
                result.get("path"),
            )
        else:
            logger.warning("score snapshot cycle failed: %s", result.get("error"))
        if reschedule and self._running:
            schedule_in_seconds(JOB_ID, self._tick, self.refresh_minutes * 60)
        return result

    def _persist_cycle_summary(self, result: Dict[str, Any]) -> None:
        summary = {
            "run_at": result.get("run_at"),
            "ok": bool(result.get("ok")),
            "count": result.get("count"),
            "written_at": result.get("written_at"),
            "path": result.get("path"),
            "error": result.get("error"),
            "skipped": result.get("skipped"),
            "phase": result.get("phase"),
            "progress": result.get("progress"),
        }
        try:
            from internal.council import weights

            path = weights.SOUL_MAP_PATH
            data = weights._load_raw(path)
            sched = data.setdefault("score_snapshot_scheduler", {})
            if isinstance(sched, dict):
                sched["last_cycle"] = summary
                weights._save_raw(data, path)
        except Exception:
            pass


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


def get_score_snapshot_scheduler_state() -> Dict[str, Any]:
    """In-process state; web workers see soul_map via loop_health cross-process merge."""
    with _lock:
        if _scheduler is None:
            return {
                "running": False,
                "age_seconds": snapshot_age_seconds(),
                "enabled": _enabled(),
            }
        return {**_scheduler.state(), "enabled": _enabled()}
