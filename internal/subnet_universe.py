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

# Netuid scan width for TMC-pagination gap probes. Bounds discovery, not membership.
MAX_NETUIDS = 200
STALE_GRACE_SECONDS = 172800  # 48h
ROOT_NETUID = 0
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
    rows: List[Dict[str, Any]] = []
    try:
        from internal.subnets.feed import registry_subnet_rows

        rows = registry_subnet_rows()
    except Exception:
        rows = _read_registry_rows()
    out: List[Dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        netuid = _netuid_of(row)
        if netuid is None or netuid == 0:
            continue
        out.append(dict(row))
    return out


def _default_tmc_fetch() -> Tuple[Set[int], Dict[int, Dict[str, Any]], bool]:
    """Return (positive netuids, rows by netuid, source_complete).

    Use TaoMarketCap pagination directly — not get_all_subnets(), which prefers the
  clipped live_subnets cache (often 75 rows) and would pin the shared universe.
    """
    try:
        from fetchers.taomarketcap import _get_all_subnets_tao

        rows = _get_all_subnets_tao() or []
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
        if not netuids:
            logger.warning("subnet_universe TMC returned zero subnets — treating as incomplete")
            return set(), {}, False
        return netuids, by_netuid, True
    except Exception as exc:
        logger.warning("subnet_universe TMC fetch failed: %s", exc)
        return set(), {}, False


def _default_probe_fetch(
    netuids: List[int],
    *,
    deadline: Optional[float] = None,
) -> Tuple[Dict[int, Optional[bool]], bool]:
    """Map netuid -> True/False from the chain's NetworksAdded registration map.

    The price call cannot tell a registered subnet from an unregistered one, because the
    chain answers 1.0 for both an unseeded pool and an unregistered netuid. Registration is
    read directly instead, at one pinned finalized block. When that read does not succeed,
    nothing is observed and ``complete`` is False, so the universe keeps its prior members.

    ``deadline`` is enforced on entry, before each RPC attempt/fallback in ``ChainReader``,
    and again before returning — a pass that finishes after expiry is incomplete.
    """
    if deadline is not None and time.monotonic() >= deadline:
        return {}, False
    try:
        from internal.chain_price.membership import get_member_netuids
        from internal.chain_price.reader import ChainReader

        reader = ChainReader(deadline_monotonic=deadline)
        global _last_registration_probe_reader
        _last_registration_probe_reader = reader
        at_hash, outcome = reader.pin_finalized_head()
        if outcome != "ok" or not at_hash:
            return {}, False
        members, outcome = get_member_netuids(reader.call_fn(), at_hash)
    except Exception as exc:
        logger.warning("subnet_universe registration read failed: %s", exc)
        return {}, False
    if outcome != "ok":
        return {}, False
    if deadline is not None and time.monotonic() >= deadline:
        return {}, False
    registered = set(members)
    observed: Dict[int, Optional[bool]] = {n: n in registered for n in netuids}
    for n in registered:
        if n not in observed:
            observed[n] = True
    return observed, True


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

    if tmc_positive is False and probe_positive is None:
        refresh_incomplete = True
        prior_validity = str(prior.get("validity") or "positive")
        if prior_validity == "negative":
            return prior_validity, sources, bool(prior.get("disputed")), negative_since, True
        if prior_validity in ("positive", "unobserved"):
            return prior_validity, sources, bool(prior.get("disputed")), None, True
        return "unobserved", sources, bool(prior.get("disputed")), None, True

    if tmc_positive is None or probe_positive is None:
        refresh_incomplete = True
        prior_validity = str(prior.get("validity") or "positive")
        if prior_validity == "negative":
            return prior_validity, sources, bool(prior.get("disputed")), negative_since, True
        if prior_validity in ("positive", "unobserved"):
            return prior_validity, sources, bool(prior.get("disputed")), None, True
        return "unobserved", sources, bool(prior.get("disputed")), None, True

    return str(prior.get("validity") or "unobserved"), sources, bool(prior.get("disputed")), negative_since, refresh_incomplete


@dataclass(frozen=True)
class DropEvidence:
    """What this cycle observed about a netuid it removed from membership."""

    tmc: Optional[bool]
    probe: Optional[bool]
    negative_since: Optional[str]


@dataclass(frozen=True)
class MembershipBuild:
    snapshot: UniverseSnapshot
    dropped: Dict[int, DropEvidence] = field(default_factory=dict)


def _eligible_for_removal(netuid: int, evidence: DropEvidence, now: datetime) -> bool:
    if netuid == ROOT_NETUID:
        return False
    if evidence.tmc is not False or evidence.probe is not False:
        return False
    if not evidence.negative_since:
        return False
    try:
        started = datetime.fromisoformat(str(evidence.negative_since))
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


def _shrink_allowed(prior: UniverseSnapshot, build: MembershipBuild) -> bool:
    """True when every netuid dropped from prior carries this cycle's removal evidence."""
    now = datetime.now(timezone.utc)
    for netuid in set(prior.netuids) - set(build.snapshot.netuids):
        evidence = build.dropped.get(netuid)
        if evidence is None or not _eligible_for_removal(netuid, evidence, now):
            return False
    return True


def _hold_prior(prior: UniverseSnapshot, status: str, message: str) -> UniverseSnapshot:
    return UniverseSnapshot(
        netuids=prior.netuids,
        rows=prior.rows,
        resolved_at=prior.resolved_at,
        status=status,
        degraded=True,
        validity_map=dict(prior.validity_map),
        cap_reached=prior.cap_reached,
        refresh_incomplete=True,
        message=message,
    )


def _compute_membership(
    prior_map: Dict[str, Any],
    *,
    tmc_positive: Set[int],
    tmc_complete: bool,
    probe_map: Dict[int, Optional[bool]],
    probe_complete: bool,
) -> Tuple[List[int], Dict[str, Any], bool, bool, Dict[int, DropEvidence]]:
    """Resolve membership; a netuid leaves only on this cycle's evidence after the 48h grace."""
    now = datetime.now(timezone.utc)
    prior_netuids = sorted(int(k) for k in prior_map.keys() if str(k).isdigit())
    candidates = set(prior_netuids) | set(tmc_positive) | {n for n, v in probe_map.items() if v is True}
    validity_map: Dict[str, Any] = {}
    dropped: Dict[int, DropEvidence] = {}
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
        entry = _validity_entry(
            validity=validity,
            sources=sources,
            disputed=disputed,
            negative_since=negative_since,
            refresh_incomplete=entry_incomplete,
        )
        evidence = DropEvidence(tmc=tmc_val, probe=probe_val, negative_since=negative_since)
        if validity == "negative" and _eligible_for_removal(netuid, evidence, now):
            dropped[netuid] = evidence
        else:
            validity_map[key] = entry

    netuids = sorted(int(k) for k in validity_map.keys())
    return netuids, validity_map, cap_reached, refresh_incomplete, dropped


def _build_rows(netuids: List[int], tmc_rows: Dict[int, Dict[str, Any]]) -> List[Dict[str, Any]]:
    registry_by_netuid: Dict[int, Dict[str, Any]] = {}
    for rec in _read_registry_rows():
        netuid = _netuid_of(rec)
        if netuid is not None:
            registry_by_netuid[netuid] = dict(rec)

    rows: List[Dict[str, Any]] = []
    for netuid in netuids:
        tmc_row = tmc_rows.get(netuid)
        registry_row = registry_by_netuid.get(netuid)
        if tmc_row is not None:
            row = dict(tmc_row)
            row.setdefault("netuid", netuid)
            row.setdefault("id", netuid)
            row["source"] = "taomarketcap"
            sources = list(row.get("sources") or [])
            if "taomarketcap" not in sources:
                sources.insert(0, "taomarketcap")
            if registry_row is not None and "registry" not in sources:
                sources.append("registry")
            row["sources"] = sources
        elif registry_row is not None:
            row = dict(registry_row)
            row.setdefault("netuid", netuid)
            row.setdefault("id", netuid)
            row["source"] = "registry"
            row["sources"] = list(row.get("sources") or ["registry"])
        else:
            # Deregistered netuid slot (no TMC or registry row): label it
            # explicitly so it never inherits a majority-vote feed label.
            row = {"netuid": netuid, "id": netuid, "source": "none", "sources": ["none"]}
        try:
            from internal.subnet_names import enrich_subnet_row

            row = enrich_subnet_row(row, use_taostats=False)
        except Exception:
            pass
        rows.append(row)
    return rows


def universe_snapshot_feed_meta(snap: UniverseSnapshot) -> Dict[str, Any]:
    """Honest /api/subnets source labels for a shared-universe snapshot."""
    from internal.subnets.feed import subnet_feed_meta

    if snap.status == "emergency_registry":
        return {"source": "registry", "sources": ["registry"]}
    rows = list(snap.rows)
    meta = subnet_feed_meta(rows)
    if meta.get("source") != "registry":
        return meta
    # Persisted rows may predate source tagging — infer from validity_map membership.
    validity = snap.validity_map or {}
    if not validity:
        return meta
    tmc_members = sum(
        1 for entry in validity.values() if "taomarketcap" in (entry.get("sources") or [])
    )
    if tmc_members > len(snap.netuids) // 2:
        return {"source": "taomarketcap", "sources": ["taomarketcap", "registry"]}
    probe_members = sum(
        1 for entry in validity.values() if "blockmachine_probe" in (entry.get("sources") or [])
    )
    if probe_members > len(snap.netuids) // 2:
        sources = ["blockmachine"]
        if tmc_members:
            sources.append("taomarketcap")
        return {"source": "blockmachine", "sources": sources}
    return meta


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
    def emergency_registry(
        cls, message: str = "", *, reason: str = "unspecified"
    ) -> "UniverseSnapshot":
        """Registry-only fallback when committed registry rows exist.

        When registry is missing, returns an empty universe with
        ``refresh_incomplete`` — never fabricates netuids 0..74.
        """
        try:
            from internal.metrics import UNIVERSE_EMERGENCY_TOTAL

            UNIVERSE_EMERGENCY_TOTAL.labels(reason=reason).inc()
        except Exception:
            pass
        logger.warning(
            "subnet_universe emergency_registry (reason=%s): %s",
            reason,
            message or "registry-only rows",
        )
        rows = _emergency_rows()
        netuids = tuple(sorted(_netuid_of(row) for row in rows if _netuid_of(row) is not None))
        incomplete = not netuids
        default_message = (
            "Registry missing — membership incomplete"
            if incomplete
            else "Registry emergency fallback — not the full approved universe"
        )
        return cls(
            netuids=netuids,
            rows=tuple(dict(row) for row in rows),
            resolved_at=_now_iso(),
            status="emergency_registry",
            degraded=True,
            validity_map={str(n): _validity_entry(validity="unobserved", sources=["registry"]) for n in netuids},
            refresh_incomplete=incomplete,
            message=message or default_message,
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

    def build(self, prior: Optional[UniverseSnapshot]) -> MembershipBuild:
        prior_map = dict((prior.validity_map if prior else {}) or {})
        tmc_positive, tmc_rows, tmc_complete = self._tmc_fetch()

        prior_keys = {int(k) for k in prior_map if str(k).isdigit()}
        candidates = set(tmc_positive) | prior_keys
        if not tmc_complete:
            probe_candidates = list(range(MAX_NETUIDS))
        else:
            candidates |= set(range(MAX_NETUIDS))
            probe_candidates = sorted(candidates)
        deadline = time.monotonic() + self._probe_budget_seconds
        if self._probe_fetch is not None:
            probe_map, probe_complete = self._probe_fetch(probe_candidates, deadline)
        else:
            probe_map, probe_complete = _default_probe_fetch(probe_candidates, deadline=deadline)

        if not tmc_complete and not probe_complete and not prior_map:
            return MembershipBuild(UniverseSnapshot.emergency_registry(reason="refresh_unresolvable"))

        netuids, validity_map, cap_reached, refresh_incomplete, dropped = _compute_membership(
            prior_map,
            tmc_positive=tmc_positive,
            tmc_complete=tmc_complete,
            probe_map=probe_map,
            probe_complete=probe_complete,
        )

        if not netuids:
            had_verified_resolution = bool(
                tmc_positive
                or any(v is not None for v in probe_map.values())
                or (prior_map and (tmc_complete or probe_complete))
            )
            if not had_verified_resolution:
                if prior and prior.netuids:
                    retain_status = (
                        "emergency_registry"
                        if prior.status == "emergency_registry"
                        else "degraded"
                    )
                    return MembershipBuild(
                        _hold_prior(prior, retain_status, "Empty membership from sources — retained prior universe")
                    )
                return MembershipBuild(
                    UniverseSnapshot.emergency_registry(
                        "Empty membership from sources — emergency registry fallback",
                        reason="empty_membership",
                    )
                )
            if prior and prior.netuids and refresh_incomplete:
                return MembershipBuild(
                    _hold_prior(prior, "degraded", "Refresh incomplete — retained last-known-good universe")
                )
            return MembershipBuild(
                UniverseSnapshot(
                    netuids=tuple(),
                    rows=tuple(),
                    resolved_at=_now_iso(),
                    status="degraded",
                    degraded=True,
                    validity_map=validity_map,
                    cap_reached=cap_reached,
                    refresh_incomplete=False,
                    message="Membership resolved empty after validation",
                ),
                dropped,
            )

        rows = _build_rows(netuids, tmc_rows)
        degraded = not (tmc_complete and probe_complete) or refresh_incomplete
        status = "degraded" if degraded else "ok"
        snapshot = UniverseSnapshot(
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
        return MembershipBuild(snapshot, dropped)


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
        reason = "lkg_missing"
        try:
            if os.path.isfile(self._persist_file):
                reason = "lkg_unusable"
                self._disk_mtime = os.path.getmtime(self._persist_file)
                with open(self._persist_file, "r") as handle:
                    payload = json.load(handle)
                if isinstance(payload, dict) and payload.get("netuids"):
                    snap = UniverseSnapshot.from_dict(payload)
                    logger.info("subnet_universe loaded LKG: %d netuids", len(snap.netuids))
                    return snap
        except Exception as exc:
            reason = "lkg_corrupt"
            logger.warning("subnet_universe corrupt/missing persistence: %s", exc)
        return UniverseSnapshot.emergency_registry(reason=reason)

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
            build = self._builder.build(self._snapshot)
            built = build.snapshot
            if built.status == "emergency_registry" and self._snapshot.status != "emergency_registry":
                logger.warning("subnet_universe refresh produced emergency — retaining LKG")
                built = _hold_prior(
                    self._snapshot, "degraded", "Refresh failed — retained last-known-good universe"
                )
            elif not _shrink_allowed(self._snapshot, build):
                logger.warning(
                    "subnet_universe unsafe shrink blocked (%d -> %d) removed=%s",
                    len(self._snapshot.netuids),
                    len(built.netuids),
                    sorted(set(self._snapshot.netuids) - set(built.netuids)),
                )
                built = _hold_prior(
                    self._snapshot, "degraded", "Unsafe shrink blocked — retained last-known-good universe"
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
            return UniverseSnapshot.emergency_registry(reason="no_usable_snapshot")
        return snap

    def replace_snapshot_for_tests(self, snap: UniverseSnapshot, *, persist: bool = False) -> None:
        self._publish(snap, persist=persist)

    def set_builder(self, builder: SnapshotBuilder) -> None:
        self._builder = builder


_provider: Optional[SubnetUniverseProvider] = None
_provider_lock = threading.Lock()
_last_registration_probe_reader: Optional[Any] = None


def registration_probe_reader() -> Optional[Any]:
    """Reader used by the last _default_probe_fetch (proof/diagnostics)."""
    return _last_registration_probe_reader


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


