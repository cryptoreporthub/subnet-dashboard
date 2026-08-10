"""Single-flight + prewarm guard for the shared learning snapshot.

Problem (2026-08-10): internal/learning/routes.py::_learning_snapshot() runs a
heavy build (predictions load + weight-trail scan) while holding a thread lock.
On a 25-50 visitor hydrate storm every request joined the same build and hit
its own timeout, so /api/learning/stats and /api/predictions/resolver served
timeout/degraded fallbacks and the page never hydrated.

This module wraps the snapshot with single-flight semantics: exactly one build
runs at a time; every other caller returns the last-good snapshot instantly
(stale-while-rebuilding). A daemon prewarm thread keeps the snapshot warm so
request paths only read cache. Installed by scripts/run_web_with_guard.py
before uvicorn imports server:app.
"""

from __future__ import annotations

import logging
import os
import threading
import time

logger = logging.getLogger(__name__)

_ORIG = None
_LOCK = threading.Lock()
_BUILDING = threading.Event()
_LAST_GOOD = {"at": 0.0, "data": None, "cold": True}
_TTL = 30.0  # matches _LEARNING_SNAPSHOT_TTL in routes.py

_COLD_FALLBACK = {
    "engine_stats": {
        "expert_weights": {},
        "accuracy": 0.0,
        "total_records": 0,
        "last_updated": None,
        "pending": 0,
        "resolved": 0,
    },
    "expert_weight_deltas": {},
    "judge_weight_deltas": {},
    "expert_graded_counts": {},
    "trust_banner": {},
    "watchdog": {},
}


def _patched():
    now = time.time()
    lg = _LAST_GOOD.get("data")
    if not _LAST_GOOD.get("cold") and isinstance(lg, dict) and now - _LAST_GOOD["at"] < _TTL:
        return lg
    if _BUILDING.is_set():
        if not _LAST_GOOD.get("cold") and isinstance(lg, dict):
            return lg
        return _COLD_FALLBACK
    if not _LOCK.acquire(blocking=False):
        if not _LAST_GOOD.get("cold") and isinstance(lg, dict):
            return lg
        return _COLD_FALLBACK
    try:
        if _BUILDING.is_set():
            if not _LAST_GOOD.get("cold") and isinstance(lg, dict):
                return lg
            return _COLD_FALLBACK
        _BUILDING.set()
        try:
            data = _ORIG()
            _LAST_GOOD.update(at=time.time(), data=data, cold=False)
            return data
        finally:
            _BUILDING.clear()
    finally:
        _LOCK.release()


def _prewarm_loop():
    interval = float(os.environ.get("LEARNING_SNAPSHOT_PREWARM_SECONDS", "10"))
    while True:
        time.sleep(interval)
        try:
            _patched()
        except Exception as exc:
            logger.debug("learning snapshot prewarm skipped: %s", exc)


def install():
    global _ORIG
    if _ORIG is not None:
        return
    from internal.learning import routes as _routes

    _ORIG = _routes._learning_snapshot
    _routes._learning_snapshot = _patched
    for mod_name in (
        "internal.learning.outcome_snapshot",
        "internal.ops.readiness",
        "internal.learning.dashboard_context",
    ):
        try:
            mod = __import__(mod_name, fromlist=["*"])
            if hasattr(mod, "_learning_snapshot") and mod._learning_snapshot is not _patched:
                mod._learning_snapshot = _patched
        except Exception as exc:
            logger.debug("snapshot guard patch skipped for %s: %s", mod_name, exc)
    threading.Thread(target=_prewarm_loop, daemon=True, name="learning-snapshot-prewarm").start()
    logger.info("learning snapshot guard installed")
