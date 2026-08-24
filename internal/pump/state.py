"""Per-subnet pump ladder state machine with hysteresis + persistence."""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import os

from internal.file_utils import safe_read_json, safe_write_json
from internal.pump.constants import (
    PHASE_EXIT_THRESHOLDS,
    PHASE_INDEX,
    PHASE_LOCK_MINUTES,
    PHASE_ORDER,
)
from internal.pump.engine import classify_signals
from internal.pump.signals import build_subnet_signals, fetch_all_subnet_signals
from internal.pump.soul_sync import apply_phase_transitions
from internal.pump.two_score import score_layer_for_phase

logger = logging.getLogger(__name__)

_lock = threading.RLock()
_scan_lock = threading.Lock()
_fetch_thread_lock = threading.Lock()
_fetch_thread: Optional[threading.Thread] = None
# ponytail: ring buffer only — upgrade path is SQLite trail if scans go sub-minute
_SCORE_TRAIL_MAX = 36
# Health is row age + coverage, not scan count. 6h matches "days-old alerts with scanned:75".
_FEED_STALL_SECONDS = int(os.environ.get("PUMP_FEED_STALL_SECONDS", str(6 * 3600)))
_MISSING_FROM_FEED_SAMPLE = 24


def _append_score_trail(entry: Dict[str, Any], score: float) -> None:
    """Append composite score sample for hero progress chart (one per ladder scan)."""
    trail = entry.get("score_trail")
    if not isinstance(trail, list):
        trail = []
    trail.append(round(float(score), 4))
    entry["score_trail"] = trail[-_SCORE_TRAIL_MAX:]


def _now_z() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_ts(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


def _minutes_between(a: Optional[str], b: datetime) -> float:
    start = _parse_ts(a)
    if start is None:
        return 0.0
    return max(0.0, (b - start).total_seconds() / 60.0)


def _resolve_path(path: Optional[str] = None) -> str:
    if path:
        return path
    from internal.pump.constants import STATE_PATH as _path

    return _path


def _netuid_int(value: Any) -> Optional[int]:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _row_age_seconds(entry: Dict[str, Any], now: Optional[datetime] = None) -> Optional[float]:
    ts = _parse_ts(entry.get("updated_at") or entry.get("last_updated"))
    if ts is None:
        return None
    now = now or datetime.now(timezone.utc)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return max(0.0, (now - ts).total_seconds())


def coverage_meta(
    data: Dict[str, Any],
    signal_netuids: Optional[List[int]] = None,
    *,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Additive ladder health: coverage + max row age, not scan-count success."""
    now = now or datetime.now(timezone.utc)
    subnets = data.get("subnets") if isinstance(data.get("subnets"), dict) else {}
    tracked: List[int] = []
    ages: List[float] = []
    for key, entry in subnets.items():
        nu = _netuid_int(entry.get("netuid") if isinstance(entry, dict) else None)
        if nu is None:
            nu = _netuid_int(key)
        if nu is not None:
            tracked.append(nu)
        if isinstance(entry, dict):
            age = _row_age_seconds(entry, now)
            if age is not None:
                ages.append(age)
    tracked_set = set(tracked)
    if signal_netuids is None:
        raw = (data.get("meta") or {}).get("last_signal_netuids")
        signal_netuids = []
        if isinstance(raw, list):
            for item in raw:
                n = _netuid_int(item)
                if n is not None:
                    signal_netuids.append(n)
    signal_set = set(signal_netuids)
    missing = sorted(tracked_set - signal_set)
    max_age = max(ages) if ages else None
    stalled = bool(missing) or (max_age is not None and max_age >= _FEED_STALL_SECONDS)
    return {
        "signal_row_count": len(signal_set),
        "missing_from_feed": missing[:_MISSING_FROM_FEED_SAMPLE],
        "missing_from_feed_count": len(missing),
        "max_row_age_seconds": int(max_age) if max_age is not None else None,
        "feed_stalled": stalled,
        "tracked_subnet_count": len(tracked_set),
    }


def load_state(path: Optional[str] = None) -> Dict[str, Any]:
    resolved = _resolve_path(path)
    with _lock:
        data = safe_read_json(resolved, default={})
        if not isinstance(data, dict):
            return {"version": "1.0", "subnets": {}, "meta": {}}
        data.setdefault("subnets", {})
        data.setdefault("meta", {})
        return data


def save_state(data: Dict[str, Any], path: Optional[str] = None) -> None:
    resolved = _resolve_path(path)
    with _lock:
        safe_write_json(resolved, data)


def _apply_hysteresis(
    current: str,
    suggested: str,
    score: float,
    since: Optional[str],
    now: datetime,
) -> str:
    """Prevent flapping: respect lock window and exit thresholds."""
    if current == suggested:
        return current

    locked = _minutes_between(since, now) < PHASE_LOCK_MINUTES
    cur_idx = PHASE_INDEX.get(current, 0)
    sug_idx = PHASE_INDEX.get(suggested, 0)
    if current != "DORMANT" and locked and suggested != "COOLING":
        # Block lateral/downgrade flapping during lock; allow upward promotion on fast pumps.
        if sug_idx <= cur_idx:
            return current

    # Downward moves allowed when score crosses exit band.
    if sug_idx < cur_idx:
        exit_threshold = PHASE_EXIT_THRESHOLDS.get(current)
        if exit_threshold is not None and score >= exit_threshold:
            return current
        return suggested

    # Upward: allow at most +1 phase per tick unless coming from DORMANT.
    if current == "DORMANT":
        return suggested
    if sug_idx > cur_idx + 1:
        return PHASE_ORDER[min(cur_idx + 1, len(PHASE_ORDER) - 1)]
    return suggested


def transition_subnet(
    state: Dict[str, Any],
    signals: Dict[str, Any],
    *,
    now: Optional[datetime] = None,
) -> Tuple[Optional[Dict[str, Any]], bool]:
    """Update one subnet entry; returns (transition_event, changed)."""
    now = now or datetime.now(timezone.utc)
    netuid = signals.get("netuid")
    if netuid is None:
        return None, False

    key = str(netuid)
    subnets = state.setdefault("subnets", {})
    entry = subnets.get(key) or {
        "netuid": netuid,
        "name": signals.get("name"),
        "phase": "DORMANT",
        "since": _now_z(),
        "composite_score": 0.0,
        "transitions": [],
    }

    classification = classify_signals(signals, current_phase=entry.get("phase", "DORMANT"))
    score = classification["composite_score"]
    accum = float(classification.get("accum_score") or 0.0)
    confirm = float(classification.get("confirm_score") or 0.0)
    suggested = classification["suggested_phase"]
    current = entry.get("phase", "DORMANT")
    new_phase = _apply_hysteresis(current, suggested, score, entry.get("since"), now)

    changed = new_phase != current
    if changed:
        transition = {
            "time": _now_z(),
            "from_phase": current,
            "to_phase": new_phase,
            "composite_score": score,
            "accum_score": accum,
            "confirm_score": confirm,
            "score_layer": classification.get("score_layer"),
            "signals": classification.get("signals"),
        }
        transitions = entry.setdefault("transitions", [])
        transitions.append(transition)
        entry["transitions"] = transitions[-50:]
        entry["phase"] = new_phase
        entry["since"] = _now_z()
        entry["last_transition"] = _now_z()
        # Cross-layer alert id — sticky from first non-dormant entry.
        if new_phase != "DORMANT" and not entry.get("alert_id"):
            import uuid

            entry["alert_id"] = uuid.uuid4().hex[:12]
        try:
            from internal.learning.pump_lead_ledger import record_pump_lead_at_phase_entry

            sig = classification.get("signals") if isinstance(classification.get("signals"), dict) else signals
            if isinstance(sig, dict) and "triad" not in sig:
                from internal.pump.triad import attach_triad_to_signals

                sig = attach_triad_to_signals(sig)
            # Freeze two-score into the claim snapshot for Upgrade 6.
            if isinstance(sig, dict):
                sig = dict(sig)
                sig["accum_score"] = accum
                sig["confirm_score"] = confirm
            record_pump_lead_at_phase_entry(
                netuid=netuid,
                name=entry.get("name"),
                phase=new_phase,
                composite_score=score,
                reference_price=float(sig.get("price") or signals.get("price") or 0),
                signal_snapshot=sig,
                alert_id=entry.get("alert_id"),
            )
        except Exception as exc:
            logger.debug("pump_lead ledger skipped SN%s: %s", netuid, exc)

    # Worker scans must never perform network name resolution for every row.
    # The feed already carries the display name; unresolved rows keep a local
    # fallback and can be refreshed by a separate, time-bounded read path.
    entry["name"] = signals.get("name") or entry.get("name") or f"SN{netuid}"
    entry["composite_score"] = score
    entry["accum_score"] = accum
    entry["confirm_score"] = confirm
    _append_score_trail(entry, score)
    entry["score_layer"] = classification.get("score_layer") or score_layer_for_phase(new_phase)
    entry["updated_at"] = _now_z()
    try:
        from internal.learning.pump_alert import _resolve_owner_wallet
        from internal.whales.service import WhaleIntelligenceService

        owner = _resolve_owner_wallet(int(netuid), signals)
        if owner:
            WhaleIntelligenceService().log_subnet_owner(owner, int(netuid))
    except Exception as exc:
        logger.debug("subnet owner log skipped SN%s: %s", netuid, exc)
    entry["signal_snapshot"] = classification.get("signals")
    subnets[key] = entry

    try:
        from internal.pump.pattern_ledger import append_ladder_sample

        sample_price = float(
            signals.get("price")
            or (classification.get("signals") or {}).get("price")
            or 0
        )
        append_ladder_sample(
            netuid,
            price=sample_price,
            phase=new_phase,
            name=entry.get("name"),
            now=now,
        )
    except Exception as exc:
        logger.debug("pattern ledger sample skipped SN%s: %s", netuid, exc)

    return (
        {
            "netuid": netuid,
            "name": entry.get("name"),
            "from_phase": current,
            "to_phase": new_phase,
            "composite_score": score,
            "accum_score": accum,
            "confirm_score": confirm,
            "score_layer": entry.get("score_layer"),
            "alert_id": entry.get("alert_id"),
        }
        if changed
        else None,
        changed,
    )


def _fetch_signal_rows_with_timeout() -> List[Dict[str, Any]]:
    """Bound signal gather so a hung merged/TMC fetch cannot wedgie ladder scans."""
    global _fetch_thread
    try:
        timeout = float(os.environ.get("PUMP_LADDER_FETCH_TIMEOUT_SECONDS", "90"))
    except ValueError:
        timeout = 90.0
    result: Dict[str, Any] = {}
    error: Dict[str, BaseException] = {}

    def _fetch() -> None:
        try:
            result["rows"] = fetch_all_subnet_signals()
        except BaseException as exc:
            error["exc"] = exc

    with _fetch_thread_lock:
        if _fetch_thread is not None and _fetch_thread.is_alive():
            logger.warning("pump ladder signal fetch skipped — previous fetch still running")
            return []
        worker = threading.Thread(target=_fetch, daemon=True, name="pump-ladder-fetch")
        _fetch_thread = worker
        worker.start()
    worker.join(timeout=timeout)
    if worker.is_alive():
        logger.warning("pump ladder signal fetch timed out after %.0fs (worker still running)", timeout)
        return []
    if "exc" in error:
        logger.warning("pump ladder signal fetch failed: %s", error["exc"])
        return []
    rows = result.get("rows")
    return rows if isinstance(rows, list) else []


def scan_all_subnets(state: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Scan ~129 subnets, apply ladder transitions, persist + Soul-Map/trail."""
    # ponytail: fetch before scan lock — long signal fetch was wedging concurrent scans.
    signal_rows = _fetch_signal_rows_with_timeout()
    if not signal_rows:
        return {"ok": False, "error": "no subnet signals", "scanned": 0, "transitions": []}
    if not _scan_lock.acquire(blocking=False):
        return {"ok": False, "error": "scan_in_progress", "scanned": 0, "transitions": []}
    try:
        return _scan_all_subnets_locked(state, signal_rows)
    finally:
        _scan_lock.release()


def _scan_all_subnets_locked(
    state: Optional[Dict[str, Any]] = None,
    signal_rows: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    rows = signal_rows or []
    if not rows:
        return {"ok": False, "error": "no subnet signals", "scanned": 0, "transitions": []}

    resolved = _resolve_path(None)
    with _lock:
        if state is not None:
            data = state
        else:
            data = safe_read_json(resolved, default={})
            if not isinstance(data, dict):
                data = {"version": "1.0", "subnets": {}, "meta": {}}
        data.setdefault("subnets", {})
        data.setdefault("meta", {})

    # ponytail: transition loop off lock — GET /api/pump-alerts load_state() must not
    # wedge behind a full ~129-subnet scan holding _lock (Fly health 503 wedge).
    transitions: List[Dict[str, Any]] = []
    signal_netuids: List[int] = []
    for row in rows:
        nu = _netuid_int(row.get("netuid") if isinstance(row, dict) else None)
        if nu is not None:
            signal_netuids.append(nu)
        event, changed = transition_subnet(data, row)
        if changed and event:
            transitions.append(event)

    data.setdefault("meta", {})
    data["meta"]["last_scan_at"] = _now_z()
    data["meta"]["tracked_subnets"] = len(data.get("subnets", {}))
    data["meta"]["last_transition_count"] = len(transitions)
    data["meta"]["last_signal_netuids"] = sorted(set(signal_netuids))
    data["meta"].update(coverage_meta(data, signal_netuids))

    phase_counts: Dict[str, int] = {p: 0 for p in PHASE_ORDER}
    for entry in data.get("subnets", {}).values():
        phase_counts[str(entry.get("phase", "DORMANT"))] = phase_counts.get(
            str(entry.get("phase", "DORMANT")), 0
        ) + 1
    data["meta"]["phase_counts"] = phase_counts

    run_at = data["meta"]["last_scan_at"]
    with _lock:
        safe_write_json(resolved, data)

    # Soul-Map / mindmap-trail write is a separate file (data/soul_map.json,
    # can be large) and must not run inside the pump-ladder _lock — it wedged
    # every load_state() caller (incl. live request paths like the mindmap
    # graph -> hourly pick -> pump overlay) for the duration of that rewrite.
    soul = apply_phase_transitions(transitions, data)

    result = {
        "ok": True,
        "run_at": run_at,
        "scanned": len(rows),
        "transitions": transitions,
        "phase_counts": phase_counts,
        "soul_map": soul,
    }
    try:
        from internal.pump.scheduler import record_ladder_scan_run

        record_ladder_scan_run(result)
    except Exception as exc:
        logger.debug("pump ladder run record skipped: %s", exc)

    return result


def get_ladder_snapshot(path: Optional[str] = None) -> Dict[str, Any]:
    return _build_ladder_payload(path)


def get_ladder(path: Optional[str] = None) -> Dict[str, Any]:
    """Public alias imported by ``internal.pump_tracker.adapter``."""
    return get_ladder_snapshot(path)


def build_ladder_snapshot(path: Optional[str] = None) -> Dict[str, Any]:
    """Alias of ``get_ladder_snapshot`` (Agent B adapter import name)."""
    return get_ladder_snapshot(path)


def _normalize_ladder_subnet(entry: Dict[str, Any]) -> Dict[str, Any]:
    """Shape persisted state rows for pump-tracker read API consumers."""
    phase = str(entry.get("phase") or entry.get("current_phase") or "DORMANT").upper()
    score = float(entry.get("composite_score") or 0.0)
    accum = float(entry.get("accum_score") or score)
    confirm = float(entry.get("confirm_score") or 0.0)
    netuid = entry.get("netuid")
    try:
        from internal.subnet_names import display_name_for_netuid

        nu = int(netuid) if netuid is not None else None
        if nu is not None:
            # Hot-path read (mindmap graph, homepage warm): name is resolved once in
            # transition_subnet during background scan; live TaoStats here blocks the
            # event loop (rate-limited time.sleep on the request thread).
            name = display_name_for_netuid(
                nu,
                ladder_hint=entry.get("name"),
                use_taostats_fallback=False,
            )
        else:
            name = entry.get("name") or "SN?"
    except Exception:
        name = entry.get("name") or f"SN{netuid}"
    try:
        from internal.pump.pattern_ledger import re_pump_prob_from_pattern

        re_pump = re_pump_prob_from_pattern(netuid)
    except Exception:
        re_pump = 0.0
    return {
        "netuid": netuid,
        "name": name,
        "current_phase": phase,
        "phase": phase,
        "composite_score": score,
        "accum_score": accum,
        "confirm_score": confirm,
        "score_layer": entry.get("score_layer") or score_layer_for_phase(phase),
        "alert_id": entry.get("alert_id"),
        "pump_score": score,
        "final_score": score,
        "pump_proneness": round(score * 100, 1),
        "re_pump_prob": re_pump,
        "since": entry.get("since"),
        "updated_at": entry.get("updated_at"),
        "last_transition": entry.get("last_transition"),
        "transitions": entry.get("transitions") or [],
    }


def _build_ladder_payload(path: Optional[str] = None) -> Dict[str, Any]:
    data = load_state(path)
    subnets_raw = [
        entry for entry in (data.get("subnets") or {}).values() if isinstance(entry, dict)
    ]
    subnets = [_normalize_ladder_subnet(entry) for entry in subnets_raw]
    subnets.sort(key=lambda s: float(s.get("composite_score") or 0), reverse=True)
    meta = dict(data.get("meta") or {})
    meta.setdefault("total_subnets", len(subnets))
    meta.setdefault("tracked_subnets", len(subnets))
    meta.setdefault("updated_at", meta.get("last_scan_at"))
    meta.update(coverage_meta(data))
    return {
        "status": "success",
        "source": "internal.pump.state",
        "meta": meta,
        "subnets": subnets,
        "count": len(subnets),
    }


def get_top_movers(limit: int = 20, path: Optional[str] = None) -> Dict[str, Any]:
    """Recent phase transitions from persisted ladder state (graceful empty list)."""
    data = load_state(path)
    rows: List[Dict[str, Any]] = []
    for entry in (data.get("subnets") or {}).values():
        if not isinstance(entry, dict):
            continue
        netuid = entry.get("netuid")
        name = entry.get("name") or f"SN{netuid}"
        for tx in entry.get("transitions") or []:
            if not isinstance(tx, dict):
                continue
            from_phase = tx.get("from_phase")
            to_phase = tx.get("to_phase")
            if not from_phase or not to_phase or from_phase == to_phase:
                continue
            max_score = float(tx.get("composite_score") or entry.get("composite_score") or 0.0)
            rows.append(
                {
                    "netuid": netuid,
                    "name": name,
                    "from_phase": from_phase,
                    "to_phase": to_phase,
                    "max_score": max_score,
                    "transition_at": tx.get("time"),
                }
            )
    rows.sort(key=lambda row: float(row.get("max_score") or 0.0), reverse=True)
    movers = rows[: max(0, int(limit))]
    return {
        "status": "success",
        "source": "internal.pump.state",
        "count": len(movers),
        "movers": movers,
    }


def classify_subnet_row(subnet: Dict[str, Any]) -> Dict[str, Any]:
    """Classify a single subnet dict without persisting (for tests)."""
    signals = build_subnet_signals(subnet)
    return classify_signals(signals)
