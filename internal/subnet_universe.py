"""Shared subnet universe membership for /api/subnets and pump feeds (D5).

D5 intentionally aligns /api/subnets and pump feeds to the approved shared
universe. This may change effective observed pump-feed coverage, as explicitly
acknowledged by the owner.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

MAX_NETUIDS = 200
STALE_GRACE_SECONDS = 172800  # 48h
REFRESH_INTERVAL_SECONDS = 300
PERSIST_VERSION = 1

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(BASE_DIR)
REGISTRY_PATH = os.path.join(REPO_ROOT, "config", "registry.json")

def _ci_or_test() -> bool:
    return bool(
        os.environ.get("GITHUB_ACTIONS") or os.environ.get("PYTEST_CURRENT_TEST") or os.environ.get("CI")
    )


def _data_dir() -> str:
    data_dir = os.environ.get("DATA_DIR", "data")
    if not os.path.isabs(data_dir):
        data_dir = os.path.join(REPO_ROOT, data_dir)
    return data_dir


def persist_path() -> str:
    return os.path.join(_data_dir(), "subnet_universe.json")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _netuid_of(rec: Dict[str, Any]) -> Optional[int]:
    for key in ("netuid", "id", "subnet_id"):
        value = rec.get(key)
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)
    return None


def _read_registry_rows() -> List[Dict[str, Any]]:
    try:
        with open(REGISTRY_PATH, "r") as handle:
            data = json.load(handle)
        if isinstance(data, dict):
            if isinstance(data.get("subnets"), list):
                return data["subnets"]
            return list(data.values())
    except Exception:
        pass
    return []


def _registry_netuids() -> List[int]:
    out: List[int] = []
    for rec in _read_registry_rows():
        netuid = _netuid_of(rec)
        if netuid is not None:
            out.append(netuid)
    return sorted(set(out))


def _emergency_rows() -> List[Dict[str, Any]]:
    try:
        from internal.subnets.feed import registry_subnet_rows

        return registry_subnet_rows()
    except Exception:
        return _read_registry_rows()


def _default_tmc_fetch() -> Tuple[Set[int], Dict[int, Dict[str, Any]], bool]:
    """Return (positive netuids, rows by netuid, source_complete)."""
    try:
        from fetchers.taomarketcap import get_all_subnets

        rows = get_all_subnets() or []
        netuids: Set[int] = set()
        by_netuid: Dict[int, Dict[str, Any]] = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            netuid = _netuid_of(row)
            if netuid is None:
                continue
            netuids.add(netuid)
            by_netuid[netuid] = dict(row)
        return netuids, by_netuid, True
    except Exception as exc:
        logger.warning("subnet_universe TMC fetch failed: %s", exc)
        return set(), {}, False


def _default_probe_fetch(
    netuids: List[int],
    *,
    deadline: Optional[float] = None,
) -> Tuple[Dict[int, Optional[bool]], bool]:
    """Map netuid -> True/False positive probe, None when unobserved."""
    observed: Dict[int, Optional[bool]] = {}
    complete = True
    try:
        from internal.chain_client import get_default_client

        client = get_default_client()
        for netuid in netuids:
            if deadline is not None and time.monotonic() >= deadline:
                complete = False
                break
            try:
                price = client.get_alpha_price(netuid)
                observed[netuid] = bool(price and float(price) > 0)
            except Exception:
                observed[netuid] = None
                complete = False
    except Exception as exc:
        logger.warning("subnet_universe probe fetch failed: %s", exc)
        return {}, False
    return observed, complete


def _validity_entry(
    *,
    validity: str,
    sources: Optional[List[str]] = None,
    disputed: bool = False,
    negative_since: Optional[str] = None,
    refresh_incomplete: bool = False,
) -> Dict[str, Any]:
    return {
        "validity": validity,
        "sources": list(sources or []),
        "disputed": disputed,
        "negative_since": negative_since,
        "refresh_incomplete": refresh_incomplete,
    }


def _merge_sources(
    prior: Optional[Dict[str, Any]],
    *,
    tmc_positive: Optional[bool],
    probe_positive: Optional[bool],
) -> Tuple[str, List[str], bool, Optional[str], bool]:
    """Return validity, sources, disputed, negative_since, refresh_incomplete."""
    prior = prior or {}
    sources = list(prior.get("sources") or [])
    negative_since = prior.get("negative_since")
    refresh_incomplete = False

    if tmc_positive is True and "taomarketcap" not in sources:
        sources.append("taomarketcap")
    if probe_positive is True and "blockmachine_probe" not in sources:
        sources.append("blockmachine_probe")

    if (tmc_positive is True and probe_positive is False) or (
        tmc_positive is False and probe_positive is True
    ):
        return "positive", sources, True, None, False

    if tmc_positive is True or probe_positive is True:
        return "positive", sources, False, None, False

    if tmc_positive is False and probe_positive is False:
        if not negative_since:
            negative_since = _now_iso()
        return "negative", sources, False, negative_since, False

    if tmc_positive is None or probe_positive is None:
        refresh_incomplete = True
        prior_validity = str(prior.get("validity") or "positive")
        if prior_validity == "negative":
            return prior_validity, sources, bool(prior.get("disputed")), negative_since, True
        if prior_validity in ("positive", "unobserved"):
            return prior_validity, sources, bool(prior.get("disputed")), None, True
        return "unobserved", sources, bool(prior.get("disputed")), None, True

    return str(prior.get("validity") or "unobserved"), sources, bool(prior.get("disputed")), negative_since, refresh_incomplete


def _eligible_for_removal(entry: Dict[str, Any], now: datetime) -> bool:
    if str(entry.get("validity")) != "negative":
        return False
    negative_since = entry.get("negative_since")
    if not negative_since:
        return False
    try:
        started = datetime.fromisoformat(str(negative_since))
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
    except Exception:
        return False
    return (now - started).total_seconds() >= STALE_GRACE_SECONDS


def is_universe_refresh_writer() -> bool:
    """Only worker processes may refresh/publish; web reloads persisted snapshots."""
    if _ci_or_test():
        return True
    try:
        from internal.run_mode import is_worker_mode

        return is_worker_mode()
    except Exception:
        return False


def _shrink_allowed(prior: UniverseSnapshot, built: UniverseSnapshot) -> bool:
    """True when a smaller built snapshot may replace prior (grace removals only)."""
    if not prior.netuids or len(built.netuids) >= len(prior.netuids):
        return True
    if built.refresh_incomplete:
        return False
    removed = set(prior.netuids) - set(built.netuids)
    if not removed:
        return True
    now = datetime.now(timezone.utc)
    for netuid in removed:
        entry = prior.validity_map.get(str(netuid)) or {}
        if not _eligible_for_removal(entry, now):
            return False
    return True


def _compute_membership(
    prior_map: Dict[str, Any],
    *,
    tmc_positive: Set[int],
    tmc_complete: bool,
    probe_map: Dict[int, Optional[bool]],
    probe_complete: bool,
) -> Tuple[List[int], Dict[str, Any], bool, bool]:
    """Resolve membership with no-shrink and 48h removal rules."""
    now = datetime.now(timezone.utc)
    prior_netuids = sorted(int(k) for k in prior_map.keys() if str(k).isdigit())
    candidates = set(prior_netuids) | set(tmc_positive) | {n for n, v in probe_map.items() if v is True}
    validity_map: Dict[str, Any] = {}
    refresh_incomplete = not (tmc_complete and probe_complete)
    cap_reached = False

    for netuid in sorted(candidates):
        key = str(netuid)
        prior_entry = prior_map.get(key) or {}
        tmc_val: Optional[bool]
        if not tmc_complete:
            tmc_val = None
        else:
            tmc_val = netuid in tmc_positive
        probe_val = probe_map.get(netuid)
        if not probe_complete and netuid not in probe_map:
            probe_val = None

        validity, sources, disputed, negative_since, entry_incomplete = _merge_sources(
            prior_entry,
            tmc_positive=tmc_val,
            probe_positive=probe_val,
        )
        refresh_incomplete = refresh_incomplete or entry_incomplete
        entry = _validity_entry(
            validity=validity,
            sources=sources,
            disputed=disputed,
            negative_since=negative_since,
            refresh_incomplete=entry_incomplete,
        )
        include = validity == "positive" or validity == "unobserved"
        if validity == "negative" and not _eligible_for_removal(entry, now):
            include = True
        if include:
            validity_map[key] = entry

    netuids = sorted(int(k) for k in validity_map.keys())
    if len(netuids) > MAX_NETUIDS:
        cap_reached = True
        netuids = netuids[:MAX_NETUIDS]
        validity_map = {str(n): validity_map[str(n)] for n in netuids}

    # Forbidden shrink: retain prior members unless explicitly removed after grace.
    for netuid in prior_netuids:
        if netuid in netuids:
            continue
        key = str(netuid)
        entry = prior_map.get(key) or _validity_entry(validity="unobserved", refresh_incomplete=True)
        if _eligible_for_removal(entry, now):
            continue
        if len(netuids) >= MAX_NETUIDS:
            cap_reached = True
            break
        validity_map[key] = dict(entry)
        validity_map[key]["refresh_incomplete"] = True
        netuids.append(netuid)
        netuids = sorted(set(netuids))

    if len(netuids) > MAX_NETUIDS:
        cap_reached = True
        netuids = sorted(netuids)[:MAX_NETUIDS]
        validity_map = {str(n): validity_map[str(n)] for n in netuids if str(n) in validity_map}

    return netuids, validity_map, cap_reached, refresh_incomplete


def _build_rows(netuids: List[int], tmc_rows: Dict[int, Dict[str, Any]]) -> List[Dict[str, Any]]:
    registry_by_netuid: Dict[int, Dict[str, Any]] = {}
    for rec in _read_registry_rows():
        netuid = _netuid_of(rec)
        if netuid is not None:
            registry_by_netuid[netuid] = dict(rec)

    rows: List[Dict[str, Any]] = []
    for netuid in netuids:
        row = dict(tmc_rows.get(netuid) or registry_by_netuid.get(netuid) or {"netuid": netuid})
        row.setdefault("netuid", netuid)
        row.setdefault("id", netuid)
        try:
            from internal.subnet_names import enrich_subnet_row

            row = enrich_subnet_row(row, use_taostats=False)
        except Exception:
            pass
        rows.append(row)
    return rows


@dataclass(frozen=True)
class UniverseSnapshot:
    netuids: Tuple[int, ...]
    rows: Tuple[Dict[str, Any], ...]
    resolved_at: Optional[str]
    status: str
    degraded: bool
    validity_map: Dict[str, Any] = field(default_factory=dict)
    cap_reached: bool = False
    refresh_incomplete: bool = False
    message: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": PERSIST_VERSION,
            "netuids": list(self.netuids),
            "rows": list(self.rows),
            "resolved_at": self.resolved_at,
            "status": self.status,
            "degraded": self.degraded,
            "validity_map": self.validity_map,
            "cap_reached": self.cap_reached,
            "refresh_incomplete": self.refresh_incomplete,
            "message": self.message,
        }

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "UniverseSnapshot":
        netuids = tuple(sorted(int(n) for n in payload.get("netuids") or []))
        rows_raw = payload.get("rows") or []
        rows = tuple(dict(row) for row in rows_raw if isinstance(row, dict))
        return cls(
            netuids=netuids,
            rows=rows,
            resolved_at=payload.get("resolved_at"),
            status=str(payload.get("status") or "ok"),
            degraded=bool(payload.get("degraded")),
            validity_map=dict(payload.get("validity_map") or {}),
            cap_reached=bool(payload.get("cap_reached")),
            refresh_incomplete=bool(payload.get("refresh_incomplete")),
            message=str(payload.get("message") or ""),
        )

    @classmethod
    def emergency_registry(cls, message: str = "") -> "UniverseSnapshot":
        rows = _emergency_rows()
        netuids = tuple(sorted(_netuid_of(row) or 0 for row in rows if _netuid_of(row) is not None))
        return cls(
            netuids=netuids,
            rows=tuple(dict(row) for row in rows),
            resolved_at=_now_iso(),
            status="emergency_registry",
            degraded=True,
            validity_map={str(n): _validity_entry(validity="unobserved", sources=["registry"]) for n in netuids},
            message=message
            or "Registry emergency fallback — not the full approved universe",
        )


class SnapshotBuilder:
    def __init__(
        self,
        *,
        tmc_fetch: Optional[Callable[[], Tuple[Set[int], Dict[int, Dict[str, Any]], bool]]] = None,
        probe_fetch: Optional[
            Callable[[List[int], float], Tuple[Dict[int, Optional[bool]], bool]]
        ] = None,
        probe_budget_seconds: float = 30.0,
    ) -> None:
        self._tmc_fetch = tmc_fetch or _default_tmc_fetch
        self._probe_fetch = probe_fetch
        self._probe_budget_seconds = probe_budget_seconds

    def build(self, prior: Optional[UniverseSnapshot]) -> UniverseSnapshot:
        prior_map = dict((prior.validity_map if prior else {}) or {})
        tmc_positive, tmc_rows, tmc_complete = self._tmc_fetch()

        probe_candidates = sorted(set(tmc_positive) | {int(k) for k in prior_map})
        if not tmc_complete and not prior_map:
            probe_candidates = list(range(MAX_NETUIDS))
        elif not tmc_complete and prior_map:
            probe_candidates = sorted({int(k) for k in prior_map})
        deadline = time.monotonic() + self._probe_budget_seconds
        if self._probe_fetch is not None:
            probe_map, probe_complete = self._probe_fetch(probe_candidates, deadline)
        else:
            probe_map, probe_complete = _default_probe_fetch(probe_candidates, deadline=deadline)

        if not tmc_complete and not probe_complete and not prior_map:
            return UniverseSnapshot.emergency_registry()

        netuids, validity_map, cap_reached, refresh_incomplete = _compute_membership(
            prior_map,
            tmc_positive=tmc_positive,
            tmc_complete=tmc_complete,
            probe_map=probe_map,
            probe_complete=probe_complete,
        )

        if not netuids and prior and prior.netuids and refresh_incomplete:
            return UniverseSnapshot(
                netuids=prior.netuids,
                rows=prior.rows,
                resolved_at=prior.resolved_at,
                status="degraded",
                degraded=True,
                validity_map=dict(prior.validity_map),
                cap_reached=prior.cap_reached,
                refresh_incomplete=True,
                message="Refresh incomplete — retained last-known-good universe",
            )

        rows = _build_rows(netuids, tmc_rows)
        degraded = not (tmc_complete and probe_complete) or refresh_incomplete
        status = "degraded" if degraded else "ok"
        if cap_reached:
            logger.warning("subnet_universe reached MAX_NETUIDS=%d cap", MAX_NETUIDS)
        return UniverseSnapshot(
            netuids=tuple(netuids),
            rows=tuple(rows),
            resolved_at=_now_iso(),
            status=status,
            degraded=degraded,
            validity_map=validity_map,
            cap_reached=cap_reached,
            refresh_incomplete=refresh_incomplete,
            message="" if not degraded else "Refresh incomplete or source degraded",
        )


class SubnetUniverseProvider:
    def __init__(self, *, persist_file: Optional[str] = None) -> None:
        self._persist_file = persist_file or persist_path()
        self._write_lock = threading.Lock()
        self._disk_mtime: float = 0.0
        self._snapshot: UniverseSnapshot = self._load_initial_snapshot()
        self._builder = SnapshotBuilder()
        self._refresh_lock = threading.Lock()
        self._refresh_thread: Optional[threading.Thread] = None
        self._loop_started = False
        self._loop_lock = threading.Lock()

    def _load_initial_snapshot(self) -> UniverseSnapshot:
        try:
            if os.path.isfile(self._persist_file):
                self._disk_mtime = os.path.getmtime(self._persist_file)
                with open(self._persist_file, "r") as handle:
                    payload = json.load(handle)
                if isinstance(payload, dict) and payload.get("netuids"):
                    snap = UniverseSnapshot.from_dict(payload)
                    logger.info("subnet_universe loaded LKG: %d netuids", len(snap.netuids))
                    return snap
        except Exception as exc:
            logger.warning("subnet_universe corrupt/missing persistence: %s", exc)
        return UniverseSnapshot.emergency_registry()

    def reload_from_disk_if_stale(self) -> UniverseSnapshot:
        """Reader path: pick up worker-published snapshot without refreshing."""
        if not os.path.isfile(self._persist_file):
            return self._snapshot
        try:
            mtime = os.path.getmtime(self._persist_file)
        except OSError:
            return self._snapshot
        if mtime <= self._disk_mtime:
            return self._snapshot
        try:
            with open(self._persist_file, "r") as handle:
                payload = json.load(handle)
            if not isinstance(payload, dict) or not payload.get("netuids"):
                return self._snapshot
            snap = UniverseSnapshot.from_dict(payload)
        except Exception as exc:
            logger.warning("subnet_universe disk reload failed: %s", exc)
            return self._snapshot
        with self._write_lock:
            self._disk_mtime = mtime
            self._snapshot = snap
        return snap

    def _atomic_persist(self, snap: UniverseSnapshot) -> None:
        if snap.status == "emergency_registry":
            return
        try:
            os.makedirs(os.path.dirname(self._persist_file), exist_ok=True)
            tmp = self._persist_file + ".tmp"
            with open(tmp, "w") as handle:
                json.dump(snap.to_dict(), handle)
            os.replace(tmp, self._persist_file)
            self._disk_mtime = os.path.getmtime(self._persist_file)
        except Exception as exc:
            logger.warning("subnet_universe persist failed: %s", exc)

    def _publish(self, snap: UniverseSnapshot, *, persist: bool = True) -> None:
        with self._write_lock:
            self._snapshot = snap
            if persist:
                self._atomic_persist(snap)

    def refresh_once(self) -> UniverseSnapshot:
        if not is_universe_refresh_writer():
            return self.reload_from_disk_if_stale()
        if not self._refresh_lock.acquire(blocking=False):
            return self._snapshot
        try:
            built = self._builder.build(self._snapshot)
            if built.status == "emergency_registry" and self._snapshot.status != "emergency_registry":
                logger.warning("subnet_universe refresh produced emergency — retaining LKG")
                built = UniverseSnapshot(
                    netuids=self._snapshot.netuids,
                    rows=self._snapshot.rows,
                    resolved_at=self._snapshot.resolved_at,
                    status="degraded",
                    degraded=True,
                    validity_map=dict(self._snapshot.validity_map),
                    cap_reached=self._snapshot.cap_reached,
                    refresh_incomplete=True,
                    message="Refresh failed — retained last-known-good universe",
                )
            elif not _shrink_allowed(self._snapshot, built):
                logger.warning(
                    "subnet_universe unsafe shrink blocked (%d -> %d)",
                    len(self._snapshot.netuids),
                    len(built.netuids),
                )
                built = UniverseSnapshot(
                    netuids=self._snapshot.netuids,
                    rows=self._snapshot.rows,
                    resolved_at=self._snapshot.resolved_at,
                    status="degraded",
                    degraded=True,
                    validity_map=dict(self._snapshot.validity_map),
                    cap_reached=self._snapshot.cap_reached,
                    refresh_incomplete=True,
                    message="Unsafe shrink blocked — retained last-known-good universe",
                )
            self._publish(built)
            return built
        finally:
            self._refresh_lock.release()

    def ensure_refresh_loop(self) -> None:
        if _ci_or_test() or not is_universe_refresh_writer():
            return
        with self._loop_lock:
            if self._loop_started:
                return
            self._loop_started = True
        threading.Thread(target=self._refresh_loop, daemon=True, name="subnet-universe-refresh").start()

    def _refresh_loop(self) -> None:
        self.refresh_once()
        while True:
            time.sleep(REFRESH_INTERVAL_SECONDS)
            try:
                self.refresh_once()
            except Exception as exc:
                logger.warning("subnet_universe refresh loop error: %s", exc)

    def kick_refresh_async(self) -> None:
        if _ci_or_test():
            return
        if not is_universe_refresh_writer():
            self.reload_from_disk_if_stale()
            return

        def _run() -> None:
            try:
                self.refresh_once()
            except Exception as exc:
                logger.warning("subnet_universe async refresh failed: %s", exc)

        threading.Thread(target=_run, daemon=True, name="subnet-universe-kick").start()

    def get_snapshot(self) -> UniverseSnapshot:
        return self._snapshot

    def get_netuids(self) -> List[int]:
        return list(self._snapshot.netuids)

    def get_lkg_or_emergency(self) -> UniverseSnapshot:
        snap = self._snapshot
        if snap.status == "emergency_registry" or not snap.netuids:
            return UniverseSnapshot.emergency_registry()
        return snap

    def replace_snapshot_for_tests(self, snap: UniverseSnapshot, *, persist: bool = False) -> None:
        self._publish(snap, persist=persist)

    def set_builder(self, builder: SnapshotBuilder) -> None:
        self._builder = builder


_provider: Optional[SubnetUniverseProvider] = None
_provider_lock = threading.Lock()


def get_provider() -> SubnetUniverseProvider:
    global _provider
    with _provider_lock:
        if _provider is None:
            _provider = SubnetUniverseProvider()
        return _provider


def get_snapshot() -> UniverseSnapshot:
    return get_provider().get_snapshot()


def get_netuids() -> List[int]:
    return get_provider().get_netuids()


def get_lkg_or_emergency() -> UniverseSnapshot:
    return get_provider().get_lkg_or_emergency()


def get_pump_membership_rows() -> List[Dict[str, Any]]:
    """Shared universe rows for pump signal membership (D5 field ix)."""
    snap = get_snapshot()
    if snap.rows:
        return [dict(row) for row in snap.rows]
    return []


def ensure_universe_reader() -> None:
    """Web/read-only path: reload persisted snapshot; never refresh/publish."""
    get_provider().reload_from_disk_if_stale()


def ensure_background_refresh() -> None:
    if is_universe_refresh_writer():
        provider = get_provider()
        provider.ensure_refresh_loop()
        provider.kick_refresh_async()
    else:
        ensure_universe_reader()


def _reset_provider_for_tests() -> None:
    global _provider
    with _provider_lock:
        _provider = None
