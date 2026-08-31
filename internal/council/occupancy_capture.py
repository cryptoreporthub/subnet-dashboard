"""Passive occupancy capture (Patch D / M7). Observe only — no cancel, no timeout bump.

GIL contention is NOT passively observable here. Check 3 records TMC-lock wait,
fcntl wait, and thread names; naming GIL requires py-spy / faulthandler at M8.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("server")

_LOCK = threading.Lock()
_MAX = 24
_events: List[Dict[str, Any]] = []
_block: List[Dict[str, Any]] = []
_thread_samples: List[Dict[str, Any]] = []
_alive: Dict[int, bool] = {}
_rest_thread_count: Optional[int] = None
_timeout_at: Dict[int, str] = {}
_persists: List[Dict[str, Any]] = []
_log_window: List[Dict[str, Any]] = []
_PROCESS_START = time.time()
_PROCESS_START_UTC = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def reset() -> None:
    with _LOCK:
        _events.clear()
        _block.clear()
        _thread_samples.clear()
        _alive.clear()
        _timeout_at.clear()
        _persists.clear()
        _log_window.clear()
        global _rest_thread_count
        _rest_thread_count = None


def _trim(buf: List[Dict[str, Any]]) -> None:
    del buf[:-_MAX]


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _thread_names() -> List[str]:
    return sorted(t.name for t in threading.enumerate())


def _capture_log(msg: str, **fields: Any) -> None:
    row = {"utc": _utc(), "msg": msg, **fields}
    with _LOCK:
        _log_window.append(row)
        _trim(_log_window)
    logger.warning("occupancy_capture %s", msg)


def note_rest_baseline() -> int:
    n = threading.active_count()
    with _LOCK:
        global _rest_thread_count
        if _rest_thread_count is None:
            _rest_thread_count = n
        return int(_rest_thread_count)


def note_tick_start(generation: int, *, overlapping: bool) -> None:
    note_rest_baseline()
    names = _thread_names()
    row = {
        "kind": "tick_start",
        "utc": _utc(),
        "generation": int(generation),
        "overlapping": bool(overlapping),
        "thread_count": len(names),
        "thread_id": threading.get_ident(),
        "mono": time.monotonic(),
    }
    with _LOCK:
        _alive[int(generation)] = True
        _events.append(row)
        _trim(_events)
        _thread_samples.append({"at": "tick_start", "n": len(names), "names": names[-16:]})
        _trim(_thread_samples)
    _capture_log(
        "generation_started generation=%s overlapping=%s" % (generation, overlapping),
        generation=int(generation),
        event="generation_started",
    )
    if overlapping:
        _capture_log(
            "retry_spawn overlapping generation=%s" % generation,
            generation=int(generation),
            event="retry_started",
        )


def note_timeout(generation: int, timeout_s: float, fut: Any) -> None:
    utc = _utc()
    row = {
        "kind": "timeout",
        "utc": utc,
        "generation": int(generation),
        "timeout_s": float(timeout_s),
        "future_running": bool(getattr(fut, "running", lambda: False)()),
        "thread_id": threading.get_ident(),
        "mono": time.monotonic(),
    }
    with _LOCK:
        _timeout_at[int(generation)] = utc
        _events.append(row)
        _trim(_events)
    _capture_log(
        "daily tick timed out generation=%s timeout_s=%s future_running=%s"
        % (generation, timeout_s, row["future_running"]),
        generation=int(generation),
        event="tick_timed_out",
    )
    _capture_log(
        "worker abandoned generation=%s" % generation,
        generation=int(generation),
        event="worker_abandoned",
    )
    for delay in (5.0, 60.0):
        _schedule_survival(int(generation), delay, fut)


def _schedule_survival(generation: int, delay_s: float, fut: Any) -> None:
    def _probe() -> None:
        running = bool(getattr(fut, "running", lambda: False)())
        names = _thread_names()
        work = [n for n in names if "daily-pick" in n]
        with _LOCK:
            _alive[generation] = running or bool(work)
            _events.append(
                {
                    "kind": "survival",
                    "utc": _utc(),
                    "generation": generation,
                    "delay_s": delay_s,
                    "future_running": running,
                    "daily_pick_threads": work,
                    "thread_count": len(names),
                    "survived_past_timeout": running or bool(work),
                }
            )
            _trim(_events)
        _capture_log(
            "generation_survival generation=%s delay_s=%s future_running=%s daily_pick_threads=%s"
            % (generation, delay_s, running, work),
            generation=generation,
            event="survival_probe",
        )

    t = threading.Timer(delay_s, _probe)
    t.daemon = True
    t.start()


def note_block(kind: str, wait_ms: float, held_ms: float = 0.0) -> None:
    row = {
        "kind": kind,
        "utc": _utc(),
        "wait_ms": round(float(wait_ms), 3),
        "held_ms": round(float(held_ms), 3),
        "thread_id": threading.get_ident(),
        "mono": time.monotonic(),
    }
    with _LOCK:
        _block.append(row)
        _trim(_block)
    _capture_log(
        "block %s wait_ms=%.1f held_ms=%.1f" % (kind, wait_ms, held_ms),
        event="lock",
        lock_kind=kind,
        wait_ms=row["wait_ms"],
        held_ms=row["held_ms"],
    )


def note_persist(site: str, *, has_write_timestamp: bool, generation: Optional[int] = None) -> None:
    """Check 5: JSON/HOLD/cache persist. Does not change write behavior."""
    utc = _utc()
    with _LOCK:
        timed_out = list(_timeout_at.keys())
        alive = dict(_alive)
        after_timeout = bool(timed_out) and (
            generation in _timeout_at if generation is not None else True
        )
        row = {
            "utc": utc,
            "site": site,
            "has_write_timestamp": bool(has_write_timestamp),
            "generation": generation,
            "after_timeout_generation": after_timeout and generation in _timeout_at
            if generation is not None
            else None,
            "timed_out_generations_alive": [g for g in timed_out if alive.get(g)],
        }
        _persists.append(row)
        _trim(_persists)


def _provenance() -> Dict[str, Any]:
    release = (os.environ.get("SENTRY_RELEASE") or os.environ.get("FLY_IMAGE_REF") or "").strip()
    machine = (os.environ.get("FLY_MACHINE_ID") or os.environ.get("FLY_ALLOC_ID") or "").strip()
    region = (os.environ.get("FLY_REGION") or "").strip()
    vm_size = (os.environ.get("FLY_VM_SIZE") or "").strip()
    process_group = (os.environ.get("FLY_PROCESS_GROUP") or "").strip()
    # ponytail: live VM topology is not in-process unless Fly injects it; never infer from fly.toml.
    identity = "unknown"
    if release and machine and region and vm_size:
        identity = release
    return {
        "deployment_identity": identity,
        "deployed_commit": release or None,
        "process_start_unix": _PROCESS_START,
        "process_start_utc": _PROCESS_START_UTC,
        "pid": os.getpid(),
        "thread_id": threading.get_ident(),
        "fly_app": (os.environ.get("FLY_APP_NAME") or "").strip() or None,
        "fly_region": region or None,
        "fly_machine_id": machine or None,
        "vm_size": vm_size or None,
        "vm_topology": None,
        "worker_config": process_group or None,
        "includes_pr_1008": "unknown",
    }


def _grade(recorded: Dict[str, Any], *, default: str, note: str) -> Dict[str, Any]:
    missing = [k for k, v in recorded.items() if v is None]
    grade = "inconclusive" if missing else default
    if grade == "pass" and missing:
        grade = "inconclusive"
    return {"grade": grade, "note": note, "missing_fields": missing, "recorded": recorded}


def snapshot() -> Dict[str, Any]:
    names = _thread_names()
    prov = _provenance()
    with _LOCK:
        overlap = any(e.get("overlapping") for e in _events if e.get("kind") == "tick_start")
        survived = [
            e for e in _events if e.get("kind") == "survival" and e.get("survived_past_timeout")
        ]
        rest = _rest_thread_count
        logs = list(_log_window)
        persists = list(_persists)
        events = list(_events)
        blocks = list(_block)
        tmc = [b for b in _block if b.get("kind") == "tmc_lock"]
        fcntl_s = [b for b in _block if b.get("kind") == "fcntl"]
        thread_samples = list(_thread_samples)
        timeout_events = [e for e in _events if e.get("kind") == "timeout"]
        last_gen = None
        for e in reversed(_events):
            if e.get("generation") is not None:
                last_gen = e.get("generation")
                break

    log_events = {str(x.get("event") or "") for x in logs}
    logs_ok = bool(
        {"tick_timed_out", "worker_abandoned", "lock"} & log_events
        or any("timed out" in str(x.get("msg")) for x in logs)
        or any(x.get("event") == "lock" for x in logs)
    )

    writes_with_ts = [p for p in persists if p.get("has_write_timestamp")]
    writes_no_ts = [p for p in persists if not p.get("has_write_timestamp")]
    stale_hits = [p for p in persists if p.get("after_timeout_generation")]
    if not persists and not timeout_events:
        check5 = {
            "status": "not_observable",
            "reason": "not captured",
            "writes": [],
        }
        g5 = "inconclusive"
    elif writes_no_ts and not writes_with_ts and not stale_hits:
        check5 = {
            "status": "not_observable",
            "reason": "checked; no timestamp at write sites",
            "writes": persists,
        }
        g5 = "inconclusive"
    elif stale_hits:
        check5 = {"status": "observed", "reason": "write after timed-out generation", "writes": persists}
        g5 = "fail"
    elif timeout_events and persists:
        check5 = {
            "status": "observed",
            "reason": "checked; persists after timeout lack generation id"
            if any(p.get("generation") is None for p in persists)
            else "checked; no stale generation persist",
            "writes": persists,
        }
        g5 = "inconclusive" if any(p.get("generation") is None for p in persists) else "pass"
    elif timeout_events:
        check5 = {
            "status": "not_observable",
            "reason": "checked; no timestamp at write sites"
            if not persists
            else "checked; no timestamp at write sites",
            "writes": persists,
        }
        g5 = "inconclusive"
    else:
        check5 = {"status": "observed", "reason": "checked; no timeout in window", "writes": persists}
        g5 = "inconclusive"

    c3_note = "gil not_passively_observable"
    if not logs_ok:
        c3_grade = "inconclusive"
        c3_note = "worker logs unavailable in window — not inferred from health samples"
    else:
        c3_grade = "inconclusive"
        c3_note = "logs correlated; GIL still not_passively_observable (M8 py-spy)"

    overlap_n = None
    if thread_samples:
        overlap_n = [s.get("n") for s in thread_samples]

    checks = {
        "generation_survival": {
            "events": events,
            "any_survived_past_timeout": bool(survived),
            "evidence": _grade(
                {
                    "utc": _utc(),
                    "generation_id": last_gen if last_gen is not None else "none",
                    "had_timeout": bool(timeout_events),
                    "deployment_identity": prov["deployment_identity"],
                },
                default="inconclusive" if not timeout_events else ("fail" if survived else "pass"),
                note="survival probes at +5s/+60s; stacks are M8",
            ),
        },
        "retry_spawn": {
            "overlapping_seen": overlap,
            "evidence": _grade(
                {
                    "utc": _utc(),
                    "generation_id": last_gen if last_gen is not None else "none",
                    "overlapping_seen": overlap,
                    "thread_count_samples": overlap_n if overlap_n is not None else [],
                    "deployment_identity": prov["deployment_identity"],
                },
                default="fail" if overlap else "inconclusive",
                note="overlap is observational; absent overlap is not a pass",
            ),
        },
        "abandoned_worker_block": {
            "samples": blocks,
            "tmc_lock": tmc,
            "fcntl": fcntl_s,
            "gil": "not_passively_observable — use py-spy/faulthandler at M8",
            "worker_log_correlation": {
                "available": logs_ok,
                "window": logs,
            },
            "evidence": _grade(
                {
                    "utc": _utc(),
                    "generation_id": last_gen if last_gen is not None else "none",
                    "lock_sample_count": len(blocks),
                    "worker_logs_available": logs_ok,
                    "deployment_identity": prov["deployment_identity"],
                },
                default=c3_grade,
                note=c3_note,
            ),
        },
        "thread_count": {
            "rest_baseline": rest,
            "now": len(names),
            "names_tail": names[-16:],
            "samples": thread_samples,
            "evidence": _grade(
                {
                    "utc": _utc(),
                    "rest_baseline": rest,
                    "now": len(names),
                    "vm_size": prov.get("vm_size"),
                    "deployment_identity": prov["deployment_identity"]
                    if prov["deployment_identity"] != "unknown"
                    else None,
                },
                default="inconclusive",
                note="thread baseline uninterpretable without live VM identity",
            ),
        },
        "stale_side_effects": {
            **check5,
            "evidence": _grade(
                {
                    "utc": _utc(),
                    "generation_id": last_gen if last_gen is not None else "none",
                    "status": check5.get("status"),
                    "deployment_identity": prov["deployment_identity"],
                },
                default=g5,
                note=str(check5.get("reason")),
            ),
        },
    }

    return {
        "patch_d": "OPEN",
        "gil": "not_passively_observable",
        "abandoned_block_hypothesis": "unproven",
        "deployment": prov,
        "executor_occupancy": {
            "daily_pick_pool": "max_workers=1",
            "pid": os.getpid(),
        },
        "checks": checks,
    }
