"""
Daily pick persistence engine for the Council.

Wraps ``select_daily_pick`` with date-based caching, regime classification,
and rotation summary so the daily pick is deterministic and auditable.
"""

from __future__ import annotations

import json
import logging
import os
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, Iterator, List, Optional

import fcntl

from internal.council.daily_pick import select_daily_pick
from internal.council.scenario_memory import classify_regime
from internal.council.rotation_tracker import get_rotation_summary
from internal.council.publish_gate import (
    directional_publish_guard,
    publish_gate_fraction,
    publish_gate_label,
)
from internal.subnets.tradable import is_tradable_subnet, subnet_netuid, subnet_volume, tradable_subnets

logger = logging.getLogger(__name__)

DAILY_PICKS_PATH = os.path.join("data", "daily_picks.json")


def _load(path: Optional[str] = None) -> List[Dict[str, Any]]:
    path = path or DAILY_PICKS_PATH
    try:
        with open(path, "r") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
    except Exception:
        pass
    return []


def _parse_iso(raw: Any) -> Optional[datetime]:
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _row_stamp(row: Optional[Dict[str, Any]]) -> Optional[datetime]:
    """When this attempt started. Legacy rows only have timestamp_utc."""
    if not isinstance(row, dict):
        return None
    return _parse_iso(row.get("build_started_at")) or _parse_iso(row.get("timestamp_utc"))


def _now_stamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@contextmanager
def _locked_daily_picks(path: str, timeout_seconds: float = 5.0) -> Iterator[None]:
    """Cross-process lock for the daily-picks read-merge-replace."""
    lock_path = path + ".lock"
    os.makedirs(os.path.dirname(lock_path) or ".", exist_ok=True)
    with open(lock_path, "a+", encoding="utf-8") as lock_file:
        deadline = time.monotonic() + timeout_seconds
        acquired = False
        while time.monotonic() < deadline:
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                break
            except (BlockingIOError, OSError):
                time.sleep(0.01)
        if not acquired:
            raise TimeoutError(
                f"Timed out after {timeout_seconds}s waiting for {lock_path}"
            )
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _save(records: List[Dict[str, Any]], path: Optional[str] = None) -> bool:
    """Persist daily picks. Return False when today's incoming row is older.

    Reloads under the file lock so an abandoned worker cannot replace a row
    whose build_started_at is later, and cannot drop history loaded by the
    winner. Same check-then-write as score snapshot publish.
    """
    path = path or DAILY_PICKS_PATH
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    incoming_today = _find_today(records)
    with _locked_daily_picks(path):
        disk = _load(path)
        disk_today = _find_today(disk)
        if (
            isinstance(incoming_today, dict)
            and incoming_today.get("scheduler_hold")
            and isinstance(disk_today, dict)
            and not disk_today.get("scheduler_hold")
            and disk_today.get("pick")
        ):
            logger.info("daily pick hold skipped: a published pick is already on disk")
            return False
        incoming_stamp = _row_stamp(incoming_today)
        disk_stamp = _row_stamp(disk_today)
        if (
            incoming_today is not None
            and incoming_stamp is not None
            and disk_stamp is not None
            and incoming_stamp < disk_stamp
        ):
            logger.info(
                "daily pick publish skipped: incoming %s is older than on-disk %s",
                incoming_today.get("build_started_at") or incoming_today.get("timestamp_utc"),
                (disk_today or {}).get("build_started_at") or (disk_today or {}).get("timestamp_utc"),
            )
            return False
        merged = _upsert_today(disk, incoming_today) if incoming_today is not None else list(records)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(merged, handle, indent=2)
        os.replace(tmp, path)
    return True


def _today_str() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _find_today(records: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    today = _today_str()
    for rec in reversed(records):
        if rec.get("date") == today:
            return rec
    return None


def _upsert_today(records: List[Dict[str, Any]], payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Replace any same-day row so scheduler regen does not duplicate dates."""
    today = _today_str()
    kept = [r for r in records if r.get("date") != today]
    kept.append(payload)
    return kept


def _subnets_have_prices(subnets: List[Dict[str, Any]]) -> bool:
    for sn in subnets:
        try:
            if float(sn.get("price") or 0) > 0:
                return True
        except (TypeError, ValueError):
            continue
    return False


def _hold_from_stale_boot_data(
    existing: Dict[str, Any],
    subnets: List[Dict[str, Any]],
) -> bool:
    """HOLD scored before subnet hydrate (missing price/volume) should regen once live."""
    if str(existing.get("action", "")).upper() != "HOLD":
        return False
    if not _subnets_have_prices(subnets):
        return False
    cand = existing.get("candidate")
    if not isinstance(cand, dict):
        return False
    sn_block = cand.get("subnet") if isinstance(cand.get("subnet"), dict) else {}
    netuid = sn_block.get("netuid") or cand.get("netuid")
    audit = cand.get("audit") if isinstance(cand.get("audit"), dict) else {}
    concerns = audit.get("concerns") or []
    if any("Missing critical field" in str(c) for c in concerns):
        return True
    try:
        cand_price = float(sn_block.get("price") or cand.get("price") or 0)
    except (TypeError, ValueError):
        cand_price = 0.0
    if cand_price <= 0 and subnet_volume(sn_block) <= 0:
        if netuid is not None:
            live = next((s for s in subnets if s.get("netuid") == netuid), None)
            if isinstance(live, dict):
                try:
                    live_price = float(live.get("price") or 0)
                except (TypeError, ValueError):
                    live_price = 0.0
                if live_price > 0 or subnet_volume(live) > 0:
                    return True
        return True
    return False


def _subnets_for_pick_creation(subnets: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Same scoring universe as pick_scheduler — never select_daily_pick on full hydrate list."""
    from internal.subnets.scoring_cap import cap_subnets_for_scoring

    sched_cap = int(os.environ.get("PICK_SCHEDULER_UNIVERSE_CAP", "24"))
    top = int(os.environ.get("TOP_SCORING_UNIVERSE", "40"))
    limit = min(sched_cap, top)
    return cap_subnets_for_scoring(subnets, limit=limit)


def _published_pick_fails_gate(payload: Dict[str, Any]) -> bool:
    """True when a cached LONG would not pass today's publish or directional gates."""
    if str(payload.get("action", "")).upper() not in ("LONG", "BUY"):
        return False
    pick = payload.get("pick")
    if not isinstance(pick, dict):
        return True
    try:
        final_confidence = float(pick.get("final_confidence", 0.0))
    except (TypeError, ValueError):
        final_confidence = 0.0
    if final_confidence < publish_gate_fraction():
        return True
    return not directional_publish_guard(pick)["approved"]


def _payload_uses_root(payload: Dict[str, Any]) -> bool:
    """True if cached pick/candidate points at Root or a missing netuid."""
    for key in ("pick", "candidate"):
        block = payload.get(key)
        if not isinstance(block, dict):
            continue
        sn = block.get("subnet") if isinstance(block.get("subnet"), dict) else block
        if isinstance(sn, dict) and not is_tradable_subnet(sn):
            n = subnet_netuid(sn)
            if n is None or n <= 0:
                return True
    return False


def write_scheduler_hold(reason: str) -> Dict[str, Any]:
    """Persist an honest HOLD when the background tick cannot finish scoring."""
    reason = (reason or "daily pick scheduler failed").strip() or "daily pick scheduler failed"
    records = _load()
    payload: Dict[str, Any] = {
        "status": "ok",
        "date": _today_str(),
        "timestamp_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "action": "HOLD",
        "reason": reason,
        "pick": None,
        "candidate": None,
        "scheduler_hold": True,
        "regime": "unknown",
        "rotation_summary": {},
        "market_context": {},
        "build_started_at": _now_stamp(),
    }
    existing = _find_today(records)
    if isinstance(existing, dict) and not existing.get("scheduler_hold") and existing.get("pick"):
        # Never clobber a real published pick.
        return existing
    records = _upsert_today(records, payload)
    if not _save(records):
        return _find_today(_load()) or existing or payload
    return payload


def get_or_create_today_pick(
    subnets: List[Dict[str, Any]],
    market_context: Optional[Dict[str, Any]] = None,
    force: bool = False,
) -> Dict[str, Any]:
    """
    Return today's daily pick, creating it if necessary.

    If ``force`` is False and a record already exists for today, the stored
    record is returned. Otherwise a new pick is generated via
    ``select_daily_pick``, optionally downgraded to HOLD when confidence is
    low, and persisted.
    """
    market_context = market_context or {}
    subnets = tradable_subnets(subnets)
    records = _load()

    if not force:
        existing = _find_today(records)
        if existing is not None and not _payload_uses_root(existing):
            # Scheduler timeout/failure HOLD — keep retrying a real score this UTC day.
            if existing.get("scheduler_hold"):
                logger.info("daily pick: regen scheduler_hold")
            # HOLD with no audited pick: attach a live candidate for display only
            # (does not change the persisted HOLD decision or invent a BUY).
            elif (
                existing.get("pick") is None
                and str(existing.get("action", "")).upper() == "HOLD"
                and subnets
                and existing.get("candidate") is None
            ):
                # ponytail: never run select_daily_pick on the read path — it wedges
                # single-worker Fly (/api/daily-pick 0-byte timeouts). Candidate is
                # optional display sugar; dossier hydrates without it.
                return existing
            elif _hold_from_stale_boot_data(existing, subnets):
                logger.info("daily pick: regen stale boot HOLD once subnets hydrated")
            elif _published_pick_fails_gate(existing):
                logger.info("daily pick: regen stale published LONG that fails publish gates")
            else:
                return existing
        # Stale Root-era cache: fall through and regenerate.

    started = _now_stamp()
    if not subnets:
        payload: Dict[str, Any] = {
            "status": "ok",
            "date": _today_str(),
            "timestamp_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "action": "HOLD",
            "reason": "No subnets available",
            "pick": None,
            "candidate": None,
            "regime": classify_regime(market_context),
            "rotation_summary": get_rotation_summary(subnets),
            "market_context": market_context,
            "build_started_at": started,
        }
        records = _upsert_today(records, payload)
        if not _save(records):
            return _find_today(_load()) or payload
        try:
            from internal.learning.prediction_loop import record_hold_decision

            record_hold_decision(reason="No subnets available", horizon_type="day")
        except Exception as exc:
            logger.warning("record_hold_decision failed (no subnets): %s", exc)
        return payload

    pick_subnets = _subnets_for_pick_creation(subnets)
    pick = select_daily_pick(pick_subnets, market_context)
    final_confidence = float(pick.get("final_confidence", 0.0))
    gate = publish_gate_fraction()
    directional_gate = directional_publish_guard(pick)

    if final_confidence < gate or not directional_gate["approved"]:
        action = "HOLD"
        stored_pick: Optional[Dict[str, Any]] = None
        reason = directional_gate["reason"] if not directional_gate["approved"] else (
            f"Confidence {final_confidence:.0%} below {publish_gate_label()} — "
            "no long call published"
        )
        candidate: Optional[Dict[str, Any]] = pick
    else:
        action = pick.get("action", "long")
        stored_pick = pick
        reason = None
        candidate = None

    payload = {
        "status": "ok",
        "date": _today_str(),
        "timestamp_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "regime": classify_regime(market_context),
        "rotation_summary": get_rotation_summary(pick_subnets),
        "action": action,
        "pick": stored_pick,
        "candidate": candidate,
        "reason": reason,
        "market_context": market_context,
        "build_started_at": started,
    }

    records = _upsert_today(records, payload)
    if not _save(records):
        return _find_today(_load()) or payload

    if stored_pick is not None:
        try:
            from internal.learning.prediction_loop import record_pick_prediction

            sn = stored_pick.get("subnet") if isinstance(stored_pick.get("subnet"), dict) else {}
            netuid = sn.get("netuid")
            subnet_row = next((s for s in subnets if s.get("netuid") == netuid), None)
            if subnet_row and float(subnet_row.get("price", 0) or 0) > 0:
                record_pick_prediction(
                    stored_pick,
                    subnet_row,
                    horizon_type="day",
                    market_context=market_context,
                )
        except Exception as exc:
            logger.warning(
                "record_pick_prediction failed for daily pick netuid=%s: %s",
                (stored_pick.get("subnet") or {}).get("netuid") if isinstance(stored_pick, dict) else None,
                exc,
            )
    elif action == "HOLD":
        try:
            from internal.learning.prediction_loop import record_hold_decision

            # Prefer live subnet row for shadow price when candidate has netuid.
            subnet_row = None
            if isinstance(candidate, dict):
                sn = candidate.get("subnet") if isinstance(candidate.get("subnet"), dict) else {}
                netuid = sn.get("netuid") or candidate.get("netuid")
                if netuid is not None:
                    subnet_row = next((s for s in subnets if s.get("netuid") == netuid), None)
            record_hold_decision(
                candidate=candidate,
                reason=reason,
                horizon_type="day",
                subnet=subnet_row,
                market_context=market_context,
            )
        except Exception as exc:
            logger.warning("record_hold_decision failed: %s", exc)

    return payload


def load_past_picks(limit: int = 7) -> List[Dict[str, Any]]:
    """Return the most recent ``limit`` daily-pick records."""
    records = _load()
    return records[-limit:] if limit else records
