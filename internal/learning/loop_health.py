"""Learning-loop health probe (Phase 0) — read-only, no scoring."""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from internal.council.resolver_scheduler import RESOLVER_REFRESH_MINUTES
from internal.council.watchdog import check_resolver_watchdog
from internal.council.weights import SOUL_MAP_PATH, _load_raw
from internal.learning.predictions_store import PREDICTIONS_PATH, load_predictions
from internal.run_mode import inline_worker_expected, is_worker_mode, split_worker_v2_enabled

logger = logging.getLogger(__name__)


def _debug_log(hypothesis_id: str, message: str, data: Dict[str, Any]) -> None:
    try:
        with open("/opt/cursor/logs/debug.log", "a", encoding="utf-8") as handle:
            handle.write(json.dumps({
                "hypothesisId": hypothesis_id,
                "location": "internal/learning/loop_health.py",
                "message": message,
                "data": data,
                "timestamp": int(time.time() * 1000),
            }) + "\n")
    except Exception:
        pass


SCORE_SNAPSHOTS_PATH = os.environ.get(
    "SCORE_SNAPSHOTS_PATH", os.path.join("data", "score_snapshots.json")
)
# Stall if pending work and resolver quieter than 2x refresh (default 30m).
_STALL_MULTIPLIER = 2
# Snapshot grace after worker boot before reporting stale (seconds).
_SNAPSHOT_BOOT_GRACE_S = int(os.environ.get("LEARNING_SNAPSHOT_BOOT_GRACE_SECONDS", "900"))
_LOOP_BOOT_GRACE_S = int(os.environ.get("LEARNING_LOOP_BOOT_GRACE_SECONDS", "300"))
_SNAPSHOT_STALE_S = int(os.environ.get("LEARNING_SNAPSHOT_STALE_SECONDS", "2700"))


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _timed_health_stage(label: str, fn, *args, **kwargs):
    started = time.perf_counter()
    try:
        return fn(*args, **kwargs)
    finally:
        logger.debug(
            "learning health stage=%s duration_ms=%.1f",
            label,
            (time.perf_counter() - started) * 1000,
        )


def _parse_iso(value: Any) -> Optional[datetime]:
    if not value or not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _daily_pick_today(path: Optional[str] = None) -> Dict[str, Any]:
    picks_path = path or os.environ.get("DAILY_PICKS_PATH", "data/daily_picks.json")
    today = _utcnow().date().isoformat()
    out: Dict[str, Any] = {
        "date": today,
        "action": None,
        "has_pick": False,
        "pick_netuid": None,
        "reason": None,
    }
    try:
        with open(picks_path, "r", encoding="utf-8") as handle:
            records = json.load(handle)
        if not isinstance(records, list):
            return out
        for rec in reversed(records):
            if not isinstance(rec, dict) or rec.get("date") != today:
                continue
            action = str(rec.get("action") or "").upper() or None
            out["action"] = action
            out["reason"] = rec.get("reason") or rec.get("hold_reason")
            pick = rec.get("pick") if isinstance(rec.get("pick"), dict) else None
            if pick:
                out["has_pick"] = True
                netuid = pick.get("netuid")
                if netuid is None:
                    sn = pick.get("subnet") if isinstance(pick.get("subnet"), dict) else {}
                    netuid = sn.get("netuid")
                out["pick_netuid"] = netuid
            break
    except Exception:
        pass
    return out


def _day_ledger_present(netuid: Any, data: Optional[Dict[str, Any]] = None) -> bool:
    """True if predictions.json has a pending or resolved day row for netuid."""
    if netuid is None:
        return False
    try:
        want = int(netuid)
    except (TypeError, ValueError):
        return False
    payload = data if isinstance(data, dict) else load_predictions()
    for bucket in ("predictions", "resolved"):
        for row in payload.get(bucket) or []:
            if not isinstance(row, dict):
                continue
            if str(row.get("horizon_type") or "hour") != "day":
                continue
            if row.get("shadow") or row.get("counterfactual"):
                continue
            try:
                if int(row.get("netuid")) == want:
                    return True
            except (TypeError, ValueError):
                continue
    return False


def _snapshot_age_seconds(
    path: Optional[str] = None,
    soul_path: Optional[str] = None,
) -> Optional[float]:
    snap_path = path or SCORE_SNAPSHOTS_PATH
    try:
        from internal.council.score_snapshots import snapshot_age_seconds

        age = snapshot_age_seconds(snap_path)
        if age is not None:
            return age
    except Exception:
        pass
    try:
        mtime = os.path.getmtime(snap_path)
        return max(0.0, _utcnow().timestamp() - mtime)
    except OSError:
        pass
    # Cross-process: worker may have written cycle summary before file flush.
    try:
        soul = _load_raw(soul_path or SOUL_MAP_PATH)
        sched = soul.get("score_snapshot_scheduler") or {}
        last = sched.get("last_cycle") if isinstance(sched, dict) else None
        if isinstance(last, dict) and last.get("run_at"):
            tick = _parse_iso(last.get("run_at"))
            if tick is not None:
                return max(0.0, (_utcnow() - tick).total_seconds())
    except Exception:
        pass
    return None


def _score_snapshot_meta(
    path: Optional[str] = None,
    soul_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Snapshot scheduler visibility for ops (file + soul_map)."""
    age = _snapshot_age_seconds(path, soul_path=soul_path)
    file_ok = False
    snap_path = path or SCORE_SNAPSHOTS_PATH
    try:
        file_ok = os.path.isfile(snap_path)
    except Exception:
        pass
    last_cycle: Dict[str, Any] = {}
    try:
        sched = (_load_raw(soul_path or SOUL_MAP_PATH).get("score_snapshot_scheduler") or {})
        if isinstance(sched, dict):
            last_cycle = sched.get("last_cycle") or {}
    except Exception:
        pass
    try:
        from internal.council.score_snapshots import get_score_snapshot_scheduler_state

        sched_state = get_score_snapshot_scheduler_state()
    except Exception:
        sched_state = {}
    return {
        "age_seconds": age,
        "file_present": file_ok,
        "last_cycle": last_cycle if isinstance(last_cycle, dict) else {},
        "scheduler": _merge_snapshot_scheduler_state(sched_state, last_cycle, soul_path),
    }


def _merge_snapshot_scheduler_state(
    mem_state: Dict[str, Any],
    soul_last_cycle: Dict[str, Any],
    soul_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Cross-process: worker runs scheduler; web reads soul_map + worker heartbeat."""
    enabled = bool(mem_state.get("enabled"))
    if not enabled:
        try:
            from internal.council.score_snapshots import _enabled

            enabled = _enabled()
        except Exception:
            enabled = False
    mem_running = bool(mem_state.get("running"))
    peer = _worker_peer()
    running = mem_running
    if (inline_worker_expected() or split_worker_v2_enabled()) and not is_worker_mode():
        running = bool(peer.get("alive")) or mem_running
    tick_at = soul_last_cycle.get("run_at") or mem_state.get("last_run_at")
    return {
        **mem_state,
        "enabled": enabled,
        "running": running,
        "last_run_at": tick_at,
        "last_run_ok": soul_last_cycle.get("ok") if soul_last_cycle else mem_state.get("last_run_ok"),
        "last_run_error": soul_last_cycle.get("error") if soul_last_cycle else mem_state.get("last_run_error"),
        "last_cycle": soul_last_cycle,
        "peer": peer.get("peer"),
    }


def _snapshot_stale(
    worker_peer: Dict[str, Any],
    snapshot_age: Optional[float],
    sched: Dict[str, Any],
) -> bool:
    """True when snapshot scheduler is enabled but volume has no fresh file/cycle."""
    if not sched.get("enabled"):
        return False
    if not inline_worker_expected() and not split_worker_v2_enabled():
        return False
    if not worker_peer.get("alive"):
        return False
    hb_age = _heartbeat_age_seconds(worker_peer)
    if hb_age is not None and hb_age < _SNAPSHOT_BOOT_GRACE_S:
        return False
    if snapshot_age is not None and snapshot_age <= _SNAPSHOT_STALE_S:
        return False
    last = sched.get("last_cycle") if isinstance(sched.get("last_cycle"), dict) else {}
    tick = _parse_iso(last.get("run_at") or sched.get("last_run_at"))
    if tick is not None:
        cycle_age = max(0.0, (_utcnow() - tick).total_seconds())
        if cycle_age <= _SNAPSHOT_STALE_S:
            return False
    return True


def _worker_peer() -> Dict[str, Any]:
    """Worker liveness — file heartbeat (inline) or HTTP probe (split v2 web)."""
    from internal.worker_peer import get_worker_peer

    return get_worker_peer()


def _last_resolver_tick(soul_path: Optional[str] = None) -> Dict[str, Any]:
    """Prefer soul_map cycle summary — survives split web/worker processes."""
    candidates: List[tuple] = []
    state: Dict[str, Any] = {}
    try:
        from internal.council.resolver_scheduler import get_prediction_resolver_scheduler_state

        state = get_prediction_resolver_scheduler_state()
        mem_at = state.get("last_run_at")
        if mem_at:
            candidates.append(
                (
                    _parse_iso(mem_at) or datetime.min.replace(tzinfo=timezone.utc),
                    mem_at,
                    state.get("last_run_ok"),
                    bool(state.get("running")),
                )
            )
    except Exception:
        state = {}
    try:
        soul = _load_raw(soul_path or SOUL_MAP_PATH)
        sched = soul.get("prediction_resolver_scheduler") or {}
        if isinstance(sched, dict):
            last = sched.get("last_cycle") or {}
            if sched.get("lifecycle"):
                lifecycle = sched.get("lifecycle")
            if isinstance(last, dict) and last.get("run_at"):
                run_at = last.get("run_at")
                candidates.append(
                    (
                        _parse_iso(run_at) or datetime.min.replace(tzinfo=timezone.utc),
                        run_at,
                        last.get("ok"),
                        True,
                    )
                )
    except Exception:
        pass
    tick, ok, mem_running = None, None, False
    lifecycle = state.get("lifecycle") or "stopped"
    if candidates:
        candidates.sort(key=lambda row: row[0], reverse=True)
        _, tick, ok, mem_running = candidates[0]
    peer = _worker_peer()
    running = mem_running or lifecycle in {"starting", "scheduled", "ticking", "running"}
    if (inline_worker_expected() or split_worker_v2_enabled()) and not is_worker_mode():
        running = bool(peer.get("alive")) or mem_running
    else:
        running = bool(mem_running)
    refresh_m = RESOLVER_REFRESH_MINUTES
    try:
        refresh_m = int(state.get("refresh_minutes") or RESOLVER_REFRESH_MINUTES)
    except Exception:
        pass
    return {
        "at": tick,
        "ok": ok,
        "running": running,
        "lifecycle": lifecycle,
        "warming": lifecycle in {"starting", "scheduled", "ticking"} and tick is None,
        "refresh_minutes": refresh_m,
        "worker_peer": peer,
    }


def _heartbeat_age_seconds(peer: Dict[str, Any]) -> Optional[float]:
    hb = peer.get("heartbeat") if isinstance(peer.get("heartbeat"), dict) else {}
    ts = _parse_iso(hb.get("ts"))
    if ts is None:
        return None
    return max(0.0, (_utcnow() - ts).total_seconds())


def _machine_restarted_since_tick(
    worker_peer: Dict[str, Any],
    tick_age_s: Optional[float],
    *,
    window_s: int = 900,
) -> bool:
    """True when inline worker heartbeat is fresh but soul_map tick predates this boot."""
    if is_worker_mode() or (not inline_worker_expected() and not split_worker_v2_enabled()):
        return False
    if not worker_peer.get("alive") or tick_age_s is None:
        return False
    hb_age = _heartbeat_age_seconds(worker_peer)
    if hb_age is None or hb_age > window_s:
        return False
    return tick_age_s > hb_age + 60.0


def build_learning_loop_health(
    *,
    daily_picks_path: Optional[str] = None,
    predictions_path: Optional[str] = None,
    snapshots_path: Optional[str] = None,
    soul_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Cheap JSON probe for pick→ledger→resolver loop status."""
    daily = _timed_health_stage("daily_pick", _daily_pick_today, daily_picks_path)

    try:
        from internal.council.pick_scheduler import (
            get_pick_scheduler_state,
            load_pick_scheduler_state_file,
        )

        pick_scheduler = _timed_health_stage("pick_scheduler", get_pick_scheduler_state)
        # Web process has BACKGROUND_ON_WEB=off — prefer worker-written volume state.
        daily_running = bool((pick_scheduler.get("daily") or {}).get("running"))
        if not daily_running:
            file_state = _timed_health_stage("pick_scheduler_file", load_pick_scheduler_state_file)
            if isinstance(file_state, dict):
                pick_scheduler = {**pick_scheduler, **file_state, "source": "volume"}
    except Exception:
        pick_scheduler = {"enabled": None, "daily": {"running": False}, "hour": {"running": False}}

    pred_path = predictions_path or PREDICTIONS_PATH
    if predictions_path:
        # Test hook: load from alternate path without mutating global.
        try:
            with open(pred_path, "r", encoding="utf-8") as handle:
                pred_data = json.load(handle)
            if not isinstance(pred_data, dict):
                pred_data = {"predictions": [], "resolved": [], "stats": {}}
        except Exception:
            pred_data = {"predictions": [], "resolved": [], "stats": {}}
    else:
        pred_data = _timed_health_stage("predictions", load_predictions)

    pending_rows: List[Any] = list(pred_data.get("predictions") or [])
    pending = len(pending_rows)
    stats = pred_data.get("stats") or {}
    if isinstance(stats.get("pending"), int) and stats["pending"] >= 0:
        pending = int(stats["pending"])

    action = (daily.get("action") or "").upper()
    is_published_long = bool(
        daily.get("has_pick")
        and action
        and action not in ("HOLD", "NONE", "")
    )
    present = (
        _day_ledger_present(daily.get("pick_netuid"), pred_data)
        if is_published_long
        else False
    )
    ledger = {
        "required": is_published_long,
        "present": present if is_published_long else False,
        "gap": bool(is_published_long and not present),
        "netuid": daily.get("pick_netuid") if is_published_long else None,
    }

    resolver = _timed_health_stage("resolver_tick", _last_resolver_tick, soul_path)
    # #region agent log
    _debug_log("E", "learning health resolver probe", {
        "running": resolver.get("running"),
        "last_tick": resolver.get("at"),
        "last_ok": resolver.get("ok"),
        "peer_alive": (resolver.get("worker_peer") or {}).get("alive"),
    })
    # #endregion
    tick_at = _parse_iso(resolver.get("at"))
    refresh_m = max(1, int(resolver.get("refresh_minutes") or RESOLVER_REFRESH_MINUTES))
    stall_after_s = refresh_m * _STALL_MULTIPLIER * 60
    tick_age_s: Optional[float] = None
    if tick_at is not None:
        tick_age_s = max(0.0, (_utcnow() - tick_at).total_seconds())

    score_snapshot = _timed_health_stage(
        "score_snapshot",
        _score_snapshot_meta,
        snapshots_path,
        soul_path=soul_path,
    )
    snapshot_age = score_snapshot.get("age_seconds")
    watchdog = _timed_health_stage("watchdog", check_resolver_watchdog, pending_rows)
    worker_peer = resolver.get("worker_peer") or {}
    hb = worker_peer.get("heartbeat") if isinstance(worker_peer.get("heartbeat"), dict) else {}
    hb_ts = _parse_iso(hb.get("ts"))
    boot_grace = False
    if hb_ts is not None:
        boot_grace = (_utcnow() - hb_ts).total_seconds() < _LOOP_BOOT_GRACE_S

    status = "ok"
    if ledger["gap"]:
        status = "stalled"
    elif worker_peer.get("expected") and worker_peer.get("alive") is False:
        status = "stalled" if not boot_grace else "degraded"
    elif watchdog.get("warning"):
        status = "stalled" if not boot_grace else "degraded"
    elif pending > 0 and (
        tick_at is None or (tick_age_s is not None and tick_age_s > stall_after_s)
    ):
        if _machine_restarted_since_tick(worker_peer, tick_age_s) and not watchdog.get("warning"):
            status = "degraded"
        elif boot_grace:
            status = "degraded"
        else:
            status = "stalled"
    elif resolver.get("warming") and boot_grace:
        status = "warming"
    elif not resolver.get("running") or tick_at is None:
        status = "degraded"
    elif _snapshot_stale(worker_peer, snapshot_age, score_snapshot.get("scheduler") or {}):
        status = "degraded"

    # #region agent log
    _debug_log("E", "learning health status", {
        "status": status,
        "pending": pending,
        "running": resolver.get("running"),
        "last_tick": resolver.get("at"),
        "boot_grace": boot_grace,
    })
    # #endregion
    return {
        "status": status,
        "checked_at": _utcnow().isoformat().replace("+00:00", "Z"),
        "pending": pending,
        "last_resolver_tick": resolver.get("at"),
        "resolver": {
            "running": resolver.get("running"),
            "lifecycle": resolver.get("lifecycle"),
            "warming": resolver.get("warming", False),
            "last_ok": resolver.get("ok"),
            "age_seconds": tick_age_s,
            "refresh_minutes": refresh_m,
            "peer": worker_peer.get("peer"),
        },
        "worker_peer": worker_peer,
        "watchdog": watchdog,
        "daily_pick": daily,
        "pick_scheduler": pick_scheduler,
        "ledger": ledger,
        "snapshot_age_seconds": snapshot_age,
        "score_snapshot": score_snapshot,
    }
