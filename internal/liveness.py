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


_PUBLIC_STRIP_FIELDS = frozenset({"last_error", "last_evidence"})


def public_liveness_registry(registry: Dict[str, Any]) -> Dict[str, Any]:
    """Strip operator-only tracker fields before any public HTTP response."""
    trackers = registry.get("trackers") or {}
    sanitized: Dict[str, Dict[str, Any]] = {}
    for name, snap in trackers.items():
        if isinstance(snap, dict):
            sanitized[name] = {
                k: v for k, v in snap.items() if k not in _PUBLIC_STRIP_FIELDS
            }
        else:
            sanitized[name] = snap
    return {**registry, "trackers": sanitized}


def hydrate_registry_trackers() -> None:
    """Ensure known trackers are registered (loads persisted soul_map on web workers)."""
    for name, interval in _known_tracker_intervals().items():
        if get_tracker(name) is None:
            LivenessTracker(name=name, interval_seconds=interval, persist=True)


def _known_tracker_intervals() -> Dict[str, int]:
    specs: Dict[str, int] = {}
    try:
        from internal.council.resolver_scheduler import RESOLVER_REFRESH_MINUTES

        specs["prediction_resolver"] = max(60, int(RESOLVER_REFRESH_MINUTES) * 60)
    except Exception:
        specs["prediction_resolver"] = 900
    try:
        from internal.council.pick_scheduler import (
            DAILY_PICK_RETRY_MINUTES,
            HOUR_PICK_REFRESH_MINUTES,
        )

        specs["daily_pick"] = max(60, int(DAILY_PICK_RETRY_MINUTES) * 60)
        specs["hour_pick"] = max(60, min(int(HOUR_PICK_REFRESH_MINUTES), 24 * 60) * 60)
    except Exception:
        pass
    try:
        from internal.pump.scheduler import PUMP_LADDER_REFRESH_MINUTES

        specs["pump_ladder"] = max(60, int(PUMP_LADDER_REFRESH_MINUTES) * 60)
    except Exception:
        specs["pump_ladder"] = 1200
    try:
        snapshot_minutes = int(os.environ.get("PUMP_DESK_SNAPSHOT_MINUTES", "15"))
        specs["pump_desk_snapshot"] = max(60, min(snapshot_minutes, 60) * 60)
    except (TypeError, ValueError):
        specs["pump_desk_snapshot"] = 900
    return specs


def _snapshot_from_persisted(name: str, interval_seconds: int) -> Optional[Dict[str, Any]]:
    """Compute a tracker snapshot from soul_map without registering in-process."""
    if read_soul_map is None:
        return None
    try:
        bucket = (read_soul_map() or {}).get(_PERSIST_PREFIX) or {}
        prior = bucket.get(name)
        if not isinstance(prior, dict):
            return None
        tracker = LivenessTracker.__new__(LivenessTracker)
        tracker.name = name
        tracker.interval_seconds = int(interval_seconds)
        tracker.staleness_factor = 2
        tracker.persist = False
        tracker.skip_limit = DEFAULT_SKIP_LIMIT
        tracker._lock = threading.Lock()
        tracker._lifecycle = str(prior.get("lifecycle", "new"))
        tracker._last_success_epoch = (
            float(prior["last_success_epoch"])
            if prior.get("last_success_epoch") is not None
            else None
        )
        tracker._last_event_epoch = (
            float(prior["last_event_epoch"])
            if prior.get("last_event_epoch") is not None
            else None
        )
        tracker._consecutive_failures = int(prior.get("consecutive_failures", 0))
        tracker._consecutive_skips = int(prior.get("consecutive_skips", 0))
        tracker._backoff_seconds = 0
        tracker._last_error = prior.get("last_error")
        tracker._last_skip_reason = prior.get("last_skip_reason")
        tracker._last_evidence = prior.get("last_evidence")
        tracker._source = "persisted"
        snap = tracker.snapshot()
        snap["source"] = "persisted"
        return snap
    except Exception:
        return None


def _merge_persisted_snapshots(local: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Prefer worker-persisted truth when web has empty in-process trackers."""

    def _freshness(snap: Dict[str, Any]) -> str:
        return str(snap.get("last_success_at") or snap.get("last_event_at") or "")

    merged = dict(local)
    for name, interval in _known_tracker_intervals().items():
        persisted = _snapshot_from_persisted(name, interval)
        if persisted is None:
            continue
        current = merged.get(name)
        if current is None:
            merged[name] = persisted
            continue
        if current.get("status") == "no_success_yet":
            merged[name] = persisted
            continue
        if persisted.get("status") == "ok" and current.get("status") != "ok":
            merged[name] = persisted
            continue
        if _freshness(persisted) > _freshness(current):
            merged[name] = persisted
    return merged


def build_liveness_registry(*, probe_worker: bool = True) -> Dict[str, Any]:
    """Registry payload for ``GET /api/liveness`` and readiness aggregation."""
    hydrate_registry_trackers()
    local = all_snapshots()
    local = _merge_persisted_snapshots(local)
    source = "inprocess"
    if probe_worker:
        try:
            from internal.data_volume import needs_worker_volume_proxy

            if needs_worker_volume_proxy():
                from internal.worker_proxy import fetch_worker_json_sync

                remote = fetch_worker_json_sync("/api/liveness")
                if isinstance(remote, dict):
                    remote_trackers = remote.get("trackers")
                    if isinstance(remote_trackers, dict) and remote_trackers:
                        merged = dict(local)
                        merged.update(remote_trackers)
                        local = merged
                        source = "merged" if all_snapshots() else "worker"
        except Exception:
            pass
    return {
        "trackers": local,
        "checked_at": _now_iso(),
        "source": source,
    }


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

        self._last_event_epoch: Optional[float] = None
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
                    ets = prior.get("last_event_epoch")
                    if ets is not None:
                        self._last_event_epoch = float(ets)
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
            self._last_event_epoch = time.time()
            self._last_skip_reason = str(reason)
        self._save()

    def record_failure(self, error: Any = "") -> None:
        with self._lock:
            self._consecutive_failures += 1
            self._last_event_epoch = time.time()
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
            self._last_event_epoch = time.time()
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
            lea = None
            ea = None
            if self._last_event_epoch is not None:
                lea = datetime.fromtimestamp(
                    self._last_event_epoch, timezone.utc
                ).isoformat()
                ea = round(max(0.0, now - self._last_event_epoch), 3)
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
                "last_event_at": lea,
                "event_age_seconds": ea,
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
                "last_event_epoch": self._last_event_epoch,
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
