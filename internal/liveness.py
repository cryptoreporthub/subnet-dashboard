"""LivenessTracker -- single honest source of scheduler health.

Contract (see handoffs/liveness-tracker-spec.md):

* status "ok" is never a stored value; it is always computed from the
  freshness of last_success_at. No code path can set ok=True.
* Skips are a first-class state and NEVER produce ok.
* "starved" requires a conjunction: a skip burst AND a stale success age.
* State persists to the soul map so restarts cannot reset honesty.
"""

from __future__ import annotations

import os
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

try:
    from internal.store.soul_map_io import read_soul_map, write_soul_map
except Exception:  # pragma: no cover - persistence degrades gracefully
    read_soul_map = None
    write_soul_map = None

_REGISTRY: Dict[str, "LivenessTracker"] = {}
_REG_LOCK = threading.Lock()

DEFAULT_SKIP_LIMIT = int(os.environ.get("LIVENESS_SKIP_LIMIT", "8"))
BACKOFF_CAP_SECONDS = int(os.environ.get("LIVENESS_BACKOFF_CAP_SECONDS", "3600"))
_PERSIST_PREFIX = "liveness"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_tracker(name: str) -> Optional["LivenessTracker"]:
    return _REGISTRY.get(name)


def all_snapshots() -> Dict[str, Dict[str, Any]]:
    """Snapshots for every registered tracker (used by /api/liveness)."""
    with _REG_LOCK:
        trackers = list(_REGISTRY.values())
    return {t.name: t.snapshot() for t in trackers}


class LivenessTracker:
    """ok is computed from last_success_at freshness; it can never be set."""

    def __init__(
        self,
        name: str,
        interval_seconds: int,
        staleness_factor: int = 2,
        persist: bool = True,
        skip_limit: Optional[int] = None,
    ) -> None:
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be > 0")
        self.name = name
        self.interval_seconds = int(interval_seconds)
        self.staleness_factor = max(1, int(staleness_factor))
        self.persist = bool(persist)
        self.skip_limit = (
            DEFAULT_SKIP_LIMIT if skip_limit is None else int(skip_limit)
        )
        self._lock = threading.Lock()
        self._lifecycle = "new"
        self._last_success_epoch: Optional[float] = None
        self._consecutive_failures = 0
        self._consecutive_skips = 0
        self._backoff_seconds = 0
        self._last_error: Optional[str] = None
        self._last_skip_reason: Optional[str] = None
        self._last_evidence: Optional[Dict[str, Any]] = None
        self._source = "inprocess"

        if self.persist and read_soul_map is not None:
            prior = None
            try:
                blob = read_soul_map() or {}
                bucket = blob.get(_PERSIST_PREFIX) or {}
                candidate = bucket.get(self.name)
                if isinstance(candidate, dict):
                    prior = candidate
            except Exception:
                prior = None
            if prior is not None:
                try:
                    ts = prior.get("last_success_epoch")
                    if ts is not None:
                        self._last_success_epoch = float(ts)
                    self._lifecycle = str(prior.get("lifecycle", "new"))
                    self._consecutive_failures = int(
                        prior.get("consecutive_failures", 0)
                    )
                    self._consecutive_skips = int(
                        prior.get("consecutive_skips", 0)
                    )
                    self._last_error = prior.get("last_error")
                    self._last_evidence = prior.get("last_evidence")
                    self._source = "persisted"
                except Exception:
                    pass

        with _REG_LOCK:
            _REGISTRY[self.name] = self

    # -- lifecycle -----------------------------------------------------

    def start(self) -> None:
        """Mark lifecycle started. NEVER touches health."""
        with self._lock:
            self._lifecycle = "started"
        self._save()

    # -- recording -----------------------------------------------------

    def record_skip(self, reason: str) -> None:
        """First-class skip. Never merged into ok or failure."""
        with self._lock:
            self._consecutive_skips += 1
            self._last_skip_reason = str(reason)
        self._save()

    def record_failure(self, error: Any = "") -> None:
        with self._lock:
            self._consecutive_failures += 1
            self._last_error = str(error)[:500]
            self._backoff_seconds = min(
                self.interval_seconds * (2 ** min(self._consecutive_failures, 10)),
                BACKOFF_CAP_SECONDS,
            )
        self._save()

    def record_success(self, evidence: Optional[Dict[str, Any]] = None) -> None:
        """The ONLY path toward ok. Requires non-empty evidence."""
        ev = dict(evidence or {})
        if not ev:
            raise ValueError(
                "record_success requires non-empty evidence "
                "(a count, an artifact path, or noop=True)"
            )
        with self._lock:
            self._last_success_epoch = time.time()
            self._consecutive_failures = 0
            self._consecutive_skips = 0
            self._backoff_seconds = 0
            self._last_evidence = ev
            self._last_error = None
            self._last_skip_reason = None
        self._save()

    # -- status (single source of truth) -------------------------------

    def _status_locked(self, now: float):
        stale_window = self.interval_seconds * self.staleness_factor
        if self._last_success_epoch is None:
            return "no_success_yet", "no recorded success yet"
        success_age = max(0.0, now - self._last_success_epoch)
        if self._consecutive_skips >= self.skip_limit and success_age > stale_window:
            return "starved", "skip burst while success stale"
        if self._consecutive_failures > 0:
            return "failing", "last tick raised"
        if success_age > stale_window:
            return "stale", "success older than interval*factor"
        return "ok", ""

    def snapshot(self) -> Dict[str, Any]:
        now = time.time()
        with self._lock:
            status, reason = self._status_locked(now)
            age = None
            if self._last_success_epoch is not None:
                age = round(max(0.0, now - self._last_success_epoch), 3)
            lsa = None
            if self._last_success_epoch is not None:
                lsa = datetime.fromtimestamp(
                    self._last_success_epoch, timezone.utc
                ).isoformat()
            return {
                "name": self.name,
                "lifecycle": self._lifecycle,
                "status": status,
                "status_reason": reason,
                "last_success_at": lsa,
                "success_age_seconds": age,
                "consecutive_failures": self._consecutive_failures,
                "consecutive_skips": self._consecutive_skips,
                "backoff_seconds": self._backoff_seconds,
                "last_error": self._last_error,
                "last_skip_reason": self._last_skip_reason,
                "last_evidence": self._last_evidence,
                "source": self._source,
            }

    # -- persistence ---------------------------------------------------

    def _save(self) -> None:
        if not self.persist or write_soul_map is None:
            return
        snap = self.snapshot()

        def mutator(blob):
            bucket = blob.setdefault(_PERSIST_PREFIX, {})
            bucket[self.name] = {
                "last_success_epoch": self._last_success_epoch,
                "lifecycle": snap["lifecycle"],
                "consecutive_failures": snap["consecutive_failures"],
                "consecutive_skips": snap["consecutive_skips"],
                "last_error": snap["last_error"],
                "last_evidence": snap["last_evidence"],
                "updated_at": _now_iso(),
            }

        try:
            write_soul_map(mutator)
        except Exception:
            pass
