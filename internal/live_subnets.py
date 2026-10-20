"""Live on-chain subnet feed (Bittensor/Substrate JSON-RPC via internal.chain_client).

Phase B1 of the subnet-dashboard hardening plan. Replaces the flaky TaoMarketCap
HTML scrape as the PRIMARY live data source for /api/subnets and the homepage,
killing the 33-day-stale registry.json fallback (audit finding #1).

Design note (deviation from IMPLEMENTATION_PLAN.md wording):
  The plan said "official bittensor SDK". This repo already ships a lightweight,
  dependency-free Bittensor-compatible JSON-RPC client in internal/chain_client.py
  (Layer 1 "primary" per its own docstring) that was never wired in. We USE that
  client instead of adding the heavy bittensor SDK (no torch bloat, reuses tested
  code). Same outcome, far less risk.

Syncing is heavy (many RPC calls), so it runs in a background daemon thread and is
cached to data/live_subnets.json with a sync timestamp. Reads are always cheap.
On any sync failure we keep the last good cache; get_all_subnets() falls back to the
existing TaoMarketCap + registry logic. The app never breaks.

SAFETY (added after a CI hang):
  - Background sync is FORCED OFF under CI / tests (GITHUB_ACTIONS, PYTEST_CURRENT_TEST, CI).
    In CI get_all_subnets() simply returns the committed registry (fast, no network).
  - Chain fetch runs in a child process (``spawn`` in prod, ``fork`` under pytest). Child entry:
    ``internal.live_subnets_fetch_child`` (minimal imports — not ``server``).
  - LIVE_SUBNETS_SYNC_TIMEOUT_SECONDS is the **RPC budget after the child signals ready**
    (module default 60). Fly web overrides to **90** (`fly.toml`); worker-v2 uses **120**.
    Spawn/import grace is LIVE_SUBNETS_SPAWN_GRACE_SECONDS (default 30) and is **not**
    charged against the RPC budget. On RPC budget expiry the child is terminate/kill so no
    orphan fetch process can wedge the web or worker (PR #906 class).
"""
from __future__ import annotations

import json
import logging
import multiprocessing
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, TypedDict, Union


class ChainFetchResult(TypedDict, total=False):
    rows: List[Dict[str, Any]]
    requested_netuids: List[int]
    completed_netuids: List[int]
    missing_netuids: List[int]
    refresh_complete: bool
    degraded_reason: Optional[str]
    batch_expired: bool
    netuid_outcomes: Dict[int, str]


FetchChainReturn = Union[ChainFetchResult, List[Dict[str, Any]], None]

logger = logging.getLogger("live_subnets")


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(BASE_DIR)
REGISTRY_PATH = os.path.join(REPO_ROOT, "config", "registry.json")


def _cache_path() -> str:
    data_dir = os.environ.get("DATA_DIR", "data")
    if not os.path.isabs(data_dir):
        data_dir = os.path.join(REPO_ROOT, data_dir)
    return os.path.join(data_dir, "live_subnets.json")


def resolve_live_row_count_from_cache(data: Dict[str, Any]) -> int:
    """Honest live-row count: explicit field wins; else derive from per-row live flags."""
    if "live_row_count" in data:
        try:
            return int(data.get("live_row_count") or 0)
        except (TypeError, ValueError):
            return 0
    subnets = data.get("subnets")
    if not isinstance(subnets, list):
        return 0
    if not any(isinstance(row, dict) and "live" in row for row in subnets):
        return 0
    return sum(
        1
        for row in subnets
        if isinstance(row, dict) and row.get("live") is True
    )


def resolve_live_row_count_from_remote(remote: Dict[str, Any]) -> int:
    """Worker freshness: never substitute aggregate subnet_count for live rows."""
    if "live_row_count" in remote:
        try:
            return int(remote.get("live_row_count") or 0)
        except (TypeError, ValueError):
            return 0
    return 0


def read_live_cache_probe() -> Dict[str, Any]:
    """Read live_subnets.json for feed/sentinel probes (no network)."""
    probe: Dict[str, Any] = {
        "exists": False,
        "count": 0,
        "live_row_count": 0,
        "synced_at": None,
        "stale": True,
        "refresh_complete": None,
    }
    path = _cache_path()
    if not os.path.isfile(path):
        return probe
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
        if not isinstance(data, dict):
            return probe
        probe["exists"] = True
        probe["count"] = int(data.get("count") or len(data.get("subnets") or []) or 0)
        probe["live_row_count"] = resolve_live_row_count_from_cache(data)
        probe["synced_at"] = data.get("synced_at")
        probe["refresh_complete"] = data.get("refresh_complete")
        synced = data.get("synced_at")
        if synced:
            parsed = datetime.fromisoformat(str(synced).replace("Z", "+00:00"))
            age = (datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)).total_seconds()
            probe["stale"] = age > MAX_STALE_SECONDS
    except Exception as exc:
        logger.debug("live cache probe read failed: %s", exc)
    return probe


def blockmachine_effective_source_active(probe: Dict[str, Any]) -> bool:
    """Fresh cache with at least one live chain row (#1357: completeness is separate)."""
    if not probe.get("exists"):
        return False
    if probe.get("stale"):
        return False
    return int(probe.get("live_row_count") or 0) > 0


def live_cache_partial_refresh(probe: Dict[str, Any]) -> bool:
    return probe.get("refresh_complete") is False and int(probe.get("live_row_count") or 0) > 0


SYNC_INTERVAL_SECONDS = int(os.environ.get("LIVE_SUBNETS_SYNC_INTERVAL_SECONDS", "300"))
MAX_STALE_SECONDS = int(os.environ.get("LIVE_SUBNETS_MAX_STALE_SECONDS", "1800"))
SYNC_TIMEOUT_SECONDS = float(os.environ.get("LIVE_SUBNETS_SYNC_TIMEOUT_SECONDS", "60"))
SPAWN_GRACE_SECONDS = float(os.environ.get("LIVE_SUBNETS_SPAWN_GRACE_SECONDS", "30"))

# Default ON in production, but FORCE-OFF in CI/test environments so the heavy
# on-chain sync never touches the network (and thus never hangs a test run).
_auto_default = os.environ.get("LIVE_SUBNETS_AUTO_SYNC", "true").lower() in ("1", "true", "yes", "on")
_in_ci_or_test = bool(
    os.environ.get("GITHUB_ACTIONS") or os.environ.get("PYTEST_CURRENT_TEST") or os.environ.get("CI")
)
AUTO_SYNC = _auto_default and not _in_ci_or_test
if _in_ci_or_test:
    logger.info("live_subnets: sync disabled in CI/test environment (AUTO_SYNC=False)")

_lock = threading.Lock()
_sync_lock = threading.Lock()
_sync_loop_running = False


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_registry() -> Dict[str, Any]:
    try:
        with open(REGISTRY_PATH, "r") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {}


def _registry_list() -> List[Dict[str, Any]]:
    reg = _read_registry()
    if isinstance(reg, dict):
        if "subnets" in reg and isinstance(reg["subnets"], list):
            return reg["subnets"]
        return list(reg.values())
    return []


def _netuid_of(rec: Dict[str, Any]) -> Optional[int]:
    for k in ("netuid", "id", "subnet_id"):
        v = rec.get(k)
        if isinstance(v, int):
            return v
        if isinstance(v, str) and v.isdigit():
            return int(v)
    return None


def chain_fetch_rows(raw: FetchChainReturn) -> List[Dict[str, Any]]:
    """Rows from ``_fetch_chain_data`` (dict or legacy list mocks)."""
    normalized = _normalize_fetch_result(raw)
    if not normalized:
        return []
    return list(normalized.get("rows") or [])


def _normalize_fetch_result(raw: FetchChainReturn) -> Optional[ChainFetchResult]:
    if raw is None:
        return None
    if isinstance(raw, list):
        completed = sorted(
            {n for n in (_netuid_of(r) for r in raw) if n is not None}
        )
        return {
            "rows": raw,
            "requested_netuids": completed,
            "completed_netuids": completed,
            "missing_netuids": [],
            "refresh_complete": True,
            "degraded_reason": None,
        }
    if isinstance(raw, dict) and "rows" in raw:
        return raw
    return None


def _merge_into_registry(live: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    by_netuid = {}
    for r in live:
        n = _netuid_of(r)
        if n is not None:
            by_netuid[n] = r
    out = []
    seen = set()
    for rec in _registry_list():
        n = _netuid_of(rec)
        if n is None:
            out.append(rec)
            continue
        seen.add(n)
        merged = dict(rec)
        lv = by_netuid.get(n)
        if lv:
            for f in ("price", "stake", "total_stake", "emission", "liquidity",
                      "total_tao", "total_alpha", "root_prop",
                      "buys_24hr", "sells_24hr", "buy_volume_24h", "sell_volume_24h"):
                if f in lv and lv[f] not in (None, ""):
                    merged[f] = lv[f]
            # RedTeam / scoring expect a single ``volume`` field.
            if merged.get("volume") in (None, ""):
                buy = float(lv.get("buy_volume_24h") or 0)
                sell = float(lv.get("sell_volume_24h") or 0)
                if buy or sell:
                    merged["volume"] = round(buy + sell, 2)
                elif lv.get("liquidity") not in (None, ""):
                    try:
                        merged["volume"] = float(lv["liquidity"])
                    except (TypeError, ValueError):
                        pass
            merged["source"] = "blockmachine"
            merged["live"] = True
        else:
            merged["live"] = False
        if merged.get("netuid") is None and n is not None:
            merged["netuid"] = n
        try:
            from internal.subnet_names import enrich_subnet_row
            merged = enrich_subnet_row(merged, use_taostats=False)
        except Exception:
            pass
        out.append(merged)
    for n, lv in by_netuid.items():
        if n not in seen:
            extra = dict(lv)
            extra["live"] = True
            extra.setdefault("source", "blockmachine")
            out.append(extra)
    return out


def _registry_netuids() -> List[int]:
    """Committed registry netuids — avoids 200-netuid RPC probe fallback."""
    out = []
    for rec in _registry_list():
        n = _netuid_of(rec)
        if n is not None:
            out.append(n)
    return sorted(set(out))


def registry_ready() -> bool:
    """The chain probe needs netuids from universe snapshot or registry; defer instead of probing empty."""
    try:
        from internal.subnet_universe import get_netuids

        netuids = get_netuids()
    except Exception:
        netuids = []
    return bool(netuids or _registry_netuids())


def _fetch_mp_context() -> multiprocessing.context.BaseContext:
    forced = os.environ.get("LIVE_SUBNETS_MP_CONTEXT", "").strip().lower()
    if forced == "spawn":
        return multiprocessing.get_context("spawn")
    if forced == "fork":
        return multiprocessing.get_context("fork")
    # ponytail: fork in pytest so monkeypatched chain_client is visible to the child.
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return multiprocessing.get_context("fork")
    return multiprocessing.get_context("spawn")


def _terminate_fetch_process(proc: multiprocessing.Process, *, grace_seconds: float = 3.0) -> None:
    if not proc.is_alive():
        return
    proc.terminate()
    proc.join(timeout=grace_seconds)
    if proc.is_alive():
        proc.kill()
        proc.join(timeout=grace_seconds)


def _fetch_chain_data():
    """Spawn fetch child; ``spawn_grace`` covers only the ready handshake.

    After ready, parent sends ``rpc_deadline_monotonic`` (absolute clock). The child
    sets its lite batch deadline to that minus ``LIVE_SUBNETS_RPC_RETURN_MARGIN_SECONDS``
    (default 3s) so executor shutdown and framed IPC send fit inside the parent's
    recv/terminate window. Parent keeps the full ``rpc_deadline`` for recv.
    """
    if not _sync_scheduling_allowed():
        logger.warning("live_subnets fetch child refused: not sync owner process")
        return None

    from internal.live_subnets_fetch_child import run_fetch_child
    from internal.live_subnets_ipc import recv_message

    rpc_budget = float(os.environ.get("LIVE_SUBNETS_SYNC_TIMEOUT_SECONDS", str(SYNC_TIMEOUT_SECONDS)))
    spawn_grace = float(os.environ.get("LIVE_SUBNETS_SPAWN_GRACE_SECONDS", str(SPAWN_GRACE_SECONDS)))
    import socket

    ctx = _fetch_mp_context()
    parent_sock, child_sock = socket.socketpair()
    parent_sock.setblocking(False)
    child_sock.setblocking(False)
    proc = ctx.Process(
        target=run_fetch_child,
        args=(child_sock,),
        name="live-subnets-fetch",
        daemon=True,
    )
    proc.start()
    child_sock.close()
    msg: Any = None
    killed = False
    try:
        boot_deadline = time.monotonic() + spawn_grace
        boot = recv_message(parent_sock, boot_deadline)
        if not isinstance(boot, dict) or boot.get("phase") != "ready":
            logger.warning(
                "live_subnets spawn grace exceeded after %.0fs; terminating fetch child",
                spawn_grace,
            )
            killed = True
            _terminate_fetch_process(proc)
            return None
        from internal.live_subnets_ipc import send_message

        rpc_deadline = time.monotonic() + rpc_budget
        if not send_message(
            parent_sock,
            {"rpc_deadline_monotonic": rpc_deadline},
            deadline=time.monotonic() + min(5.0, rpc_budget),
        ):
            logger.warning("live_subnets failed to send RPC deadline to fetch child")
            killed = True
            _terminate_fetch_process(proc)
            return None
        msg = recv_message(parent_sock, rpc_deadline)
        if msg is None:
            if time.monotonic() >= rpc_deadline:
                logger.warning(
                    "live_subnets RPC budget exceeded after %.0fs; terminating fetch child",
                    rpc_budget,
                )
            else:
                logger.warning(
                    "live_subnets fetch child closed before result (send failure or crash)"
                )
            killed = True
            _terminate_fetch_process(proc)
            return None
    finally:
        try:
            parent_sock.close()
        except Exception:
            pass
        proc.join(timeout=1.0)
        if proc.is_alive():
            _terminate_fetch_process(proc)

    if killed or not isinstance(msg, dict):
        logger.warning("live_subnets sync failed: invalid child response")
        return None
    if not msg.get("ok"):
        logger.warning("live_subnets sync failed: %s", msg.get("exc"))
        return None
    rows = msg.get("data")
    if not isinstance(rows, list):
        return None
    return {
        "rows": rows,
        "requested_netuids": list(msg.get("requested_netuids") or []),
        "completed_netuids": list(msg.get("completed_netuids") or []),
        "missing_netuids": list(msg.get("missing_netuids") or []),
        "refresh_complete": bool(msg.get("refresh_complete", not msg.get("missing_netuids"))),
        "degraded_reason": msg.get("degraded_reason"),
        "batch_expired": bool(msg.get("batch_expired")),
        "netuid_outcomes": {
            int(k): str(v)
            for k, v in (msg.get("netuid_outcomes") or {}).items()
        },
    }


def _boot_status_path() -> str:
    return os.path.join(os.path.dirname(_cache_path()), "live_subnets_boot.json")


def _record_boot_status(**fields: Any) -> None:
    try:
        payload = {"at": _now_iso(), **fields}
        path = _boot_status_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(payload, f)
        os.replace(tmp, path)
    except Exception as exc:
        logger.debug("live_subnets boot status write failed: %s", exc)


def _read_boot_status() -> Dict[str, Any]:
    try:
        path = _boot_status_path()
        if os.path.isfile(path):
            with open(path, "r") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        pass
    return {}


def _sync_once() -> bool:
    # ponytail: bootstrap + sync loop can both call _sync_once — one guard here.
    if not _sync_lock.acquire(blocking=False):
        logger.debug("live_subnets sync skipped — already in flight")
        return False
    _record_boot_status(phase="sync_start")
    try:
        if not registry_ready():
            _record_boot_status(
                phase="deferred",
                ok=False,
                reason="registry_not_ready",
                rows=0,
            )
            logger.info("live_subnets sync deferred until registry is ready")
            return False
        fetch = _normalize_fetch_result(_fetch_chain_data())
        if fetch is None:
            logger.warning("live_subnets sync: chain fetch failed or timed out")
            _record_boot_status(phase="sync_done", ok=False, reason="timeout")
            return False
        rows = fetch.get("rows") or []
        if not rows:
            empty_reason = "empty_netuids" if not _registry_netuids() else "empty"
            logger.warning("live_subnets sync: chain fetch returned 0 subnets (%s)", empty_reason)
            _record_boot_status(phase="sync_done", ok=False, reason=empty_reason, rows=0)
            return False
        merged = _merge_into_registry(rows)
        refresh_complete = bool(fetch.get("refresh_complete", True))
        payload = {
            "synced_at": _now_iso(),
            "source": "blockmachine",
            "count": len(merged),
            "live_row_count": len(rows),
            "subnets": merged,
            "requested_netuids": fetch.get("requested_netuids") or [],
            "completed_netuids": fetch.get("completed_netuids") or [],
            "missing_netuids": fetch.get("missing_netuids") or [],
            "refresh_complete": refresh_complete,
            "degraded_reason": fetch.get("degraded_reason"),
            "batch_expired": bool(fetch.get("batch_expired")),
            "netuid_outcomes": fetch.get("netuid_outcomes") or {},
        }
        try:
            os.makedirs(os.path.dirname(_cache_path()), exist_ok=True)
            tmp = _cache_path() + ".tmp"
            with open(tmp, "w") as f:
                json.dump(payload, f)
            os.replace(tmp, _cache_path())
            if refresh_complete:
                logger.info("live_subnets sync OK: %d subnets (%d live rows)", len(merged), len(rows))
                _record_boot_status(
                    phase="sync_done",
                    ok=True,
                    rows=len(merged),
                    live_rows=len(rows),
                    refresh_complete=True,
                )
                return True
            reason = fetch.get("degraded_reason") or "partial_fetch"
            logger.warning(
                "live_subnets partial sync: %d live rows, %d merged, missing=%s",
                len(rows),
                len(merged),
                fetch.get("missing_netuids"),
            )
            _record_boot_status(
                phase="sync_done",
                ok=False,
                reason=reason,
                rows=len(merged),
                live_rows=len(rows),
                refresh_complete=False,
                missing_netuids=fetch.get("missing_netuids") or [],
            )
            return False
        except Exception as exc:
            logger.warning("live_subnets cache write failed: %s", exc)
            _record_boot_status(phase="sync_done", ok=False, reason=f"write:{exc}")
            return False
    except Exception as exc:
        logger.warning("live_subnets sync unexpected error: %s", exc)
        _record_boot_status(phase="sync_done", ok=False, reason=f"error:{exc}")
        return False
    finally:
        _sync_lock.release()


def _sync_scheduling_allowed() -> bool:
    if not AUTO_SYNC:
        return False
    from internal.run_mode import live_subnets_sync_owner_enabled

    return live_subnets_sync_owner_enabled()


def bootstrap_live_subnets_cache() -> bool:
    """One-shot chain sync on dedicated worker boot (LIVE_SUBNETS_BOOT_IMMEDIATE=on)."""
    if not _sync_scheduling_allowed():
        return False
    if _in_ci_or_test:
        return False
    if not registry_ready():
        _record_boot_status(
            phase="deferred",
            ok=False,
            reason="registry_not_ready",
            rows=0,
        )
        logger.info("live_subnets bootstrap deferred until registry is ready")
        return False

    # Dedicated worker respects LIVE_SUBNETS_BOOT_IMMEDIATE like web inline worker.
    flag = os.environ.get("LIVE_SUBNETS_BOOT_IMMEDIATE", "off").strip().lower()
    if flag not in ("1", "true", "yes", "on"):
        return False
    logger.info("live_subnets bootstrap immediate sync")
    return _sync_once()


def get_live_subnets() -> List[Dict[str, Any]]:
    try:
        if os.path.exists(_cache_path()):
            with open(_cache_path(), "r") as f:
                data = json.load(f)
            subnets = data.get("subnets", [])
            if subnets:
                return subnets
    except Exception:
        pass
    return _registry_list()


def start_live_subnets_sync() -> None:
    """Owner-only entry: start the background sync loop (idempotent)."""
    if not _sync_scheduling_allowed():
        return
    if os.environ.get("PYTEST_CURRENT_TEST") or os.environ.get("GITHUB_ACTIONS") or os.environ.get("CI"):
        return
    _ensure_sync_loop()


def _ensure_sync_loop() -> None:
    global _sync_loop_running
    if not _sync_scheduling_allowed():
        return
    if os.environ.get("PYTEST_CURRENT_TEST") or os.environ.get("GITHUB_ACTIONS") or os.environ.get("CI"):
        return
    with _lock:
        if _sync_loop_running:
            return
        _sync_loop_running = True
    logger.info("live_subnets sync loop starting (owner process)")
    t = threading.Thread(target=_sync_loop, daemon=True, name="live-subnets-sync")
    t.start()


def _sync_loop() -> None:
    global _sync_loop_running
    try:
        _sync_once()
        while True:
            time.sleep(SYNC_INTERVAL_SECONDS)
            _sync_once()
    except Exception as exc:
        logger.warning("live_subnets sync loop exited: %s", exc)
    finally:
        _sync_loop_running = False


def live_data_freshness() -> Dict[str, Any]:
    try:
        from internal.data_volume import worker_data_freshness

        remote = worker_data_freshness()
        if remote:
            return remote
    except Exception:
        pass
    info = {
        "source": "blockmachine",
        "sync_enabled": AUTO_SYNC,
        "ci_or_test": _in_ci_or_test,
        "last_sync": None,
        "age_seconds": None,
        "subnet_count": 0,
        "stale": True,
        "cache_path": _cache_path(),
        "cache_present": False,
    }
    try:
        if os.path.exists(_cache_path()):
            info["cache_present"] = True
            with open(_cache_path(), "r") as f:
                data = json.load(f)
            info["last_sync"] = data.get("synced_at")
            info["subnet_count"] = data.get("count", 0)
            info["live_row_count"] = resolve_live_row_count_from_cache(data)
            info["requested_netuids"] = data.get("requested_netuids") or []
            info["completed_netuids"] = data.get("completed_netuids") or []
            info["missing_netuids"] = data.get("missing_netuids") or []
            info["refresh_complete"] = data.get("refresh_complete")
            info["degraded_reason"] = data.get("degraded_reason")
            info["batch_expired"] = data.get("batch_expired")
            raw_outcomes = data.get("netuid_outcomes") or {}
            info["netuid_outcomes"] = {
                int(k): str(v) for k, v in raw_outcomes.items() if str(k).isdigit() or isinstance(k, int)
            }
            if data.get("synced_at"):
                age = (datetime.now(timezone.utc) - datetime.fromisoformat(data["synced_at"])).total_seconds()
                info["age_seconds"] = int(age)
                # Age-only stale: partial lite fetch is surfaced via refresh_complete / degraded_reason.
                info["stale"] = age > MAX_STALE_SECONDS
    except Exception as exc:
        logger.debug("freshness read failed: %s", exc)
    try:
        from internal.subnets.feed import probe_feed_layers

        probe = probe_feed_layers()
        info["effective_source"] = probe.get("effective_source")
        info["effective_total"] = probe.get("likely_total")
        info["registry_count"] = probe.get("registry_count")
        info["tmc_cache_count"] = (probe.get("tmc_cache") or {}).get("count", 0)
    except Exception as exc:
        logger.debug("effective feed probe failed: %s", exc)
    try:
        from internal.chain_client import get_default_client

        info["rpc_healthy"] = get_default_client().is_healthy()
    except Exception:
        info["rpc_healthy"] = None
    try:
        from internal.run_mode import get_run_mode, worker_heavy_feeds_enabled

        info["run_mode"] = get_run_mode()
        info["worker_heavy"] = worker_heavy_feeds_enabled()
    except Exception:
        pass
    boot = _read_boot_status()
    if boot:
        info["boot_status"] = boot
    if info.get("run_mode") == "worker":
        try:
            from internal.chain_client import get_default_client

            info["sample_price_sn1"] = get_default_client().get_alpha_price(1)
        except Exception as exc:
            info["sample_price_sn1"] = None
            info["sample_price_error"] = str(exc)[:120]
    return info
