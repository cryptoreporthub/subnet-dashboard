"""Heal daily-pick → predictions.json ledger gaps (Acc-0).

When today's published LONG exists in ``daily_picks.json`` but no gradeable day
row exists in ``predictions.json`` (common after an accuracy epoch reset), this
module idempotently backfills via ``record_pick_prediction``.
"""

from __future__ import annotations

import json
import fcntl
import hashlib
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from internal.learning.loop_health import _daily_pick_today, _day_ledger_present
from internal.learning import predictions_store

logger = logging.getLogger(__name__)

DAILY_PICKS_PATH = os.environ.get("DAILY_PICKS_PATH", "data/daily_picks.json")
ARCHIVE_DIR = os.environ.get("PREDICTIONS_ARCHIVE_DIR", "data/predictions_archive")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _today_record(path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    picks_path = path or DAILY_PICKS_PATH
    today = _utcnow().date().isoformat()
    try:
        with open(picks_path, "r", encoding="utf-8") as handle:
            records = json.load(handle)
    except Exception:
        return None
    if not isinstance(records, list):
        return None
    for rec in reversed(records):
        if isinstance(rec, dict) and rec.get("date") == today:
            return rec
    return None


def _subnet_row_for_heal(stored_pick: Dict[str, Any], netuid: Any) -> Optional[Dict[str, Any]]:
    """Best-effort subnet row with positive reference price for ledger backfill."""
    sn = stored_pick.get("subnet") if isinstance(stored_pick.get("subnet"), dict) else {}
    row: Dict[str, Any] = dict(sn) if sn else {}
    row.setdefault("netuid", netuid)
    try:
        price = float(row.get("price") or 0)
    except (TypeError, ValueError):
        price = 0.0
    if price > 0:
        return row

    pred = stored_pick.get("prediction") if isinstance(stored_pick.get("prediction"), dict) else {}
    snap = pred.get("subnet_snapshot") if isinstance(pred.get("subnet_snapshot"), dict) else {}
    try:
        snap_price = float(
            snap.get("price") or pred.get("reference_price") or stored_pick.get("reference_price") or 0
        )
    except (TypeError, ValueError):
        snap_price = 0.0
    if snap_price > 0:
        row["price"] = snap_price
        if not row.get("name"):
            row["name"] = snap.get("name") or f"SN{netuid}"
        return row

    try:
        from internal.live_subnets import get_live_subnets

        live = next((s for s in get_live_subnets() if s.get("netuid") == netuid), None)
        if isinstance(live, dict):
            try:
                live_price = float(live.get("price") or 0)
            except (TypeError, ValueError):
                live_price = 0.0
            if live_price > 0:
                return dict(live)
    except Exception as exc:
        logger.debug("ledger heal live subnet lookup failed SN%s: %s", netuid, exc)

    return None


def heal_daily_pick_ledger(
    *,
    dry_run: bool = False,
    daily_picks_path: Optional[str] = None,
    predictions_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Backfill missing day ledger row for today's published LONG."""
    picks_path = daily_picks_path or DAILY_PICKS_PATH
    pred_path = predictions_path or predictions_store.PREDICTIONS_PATH

    from internal.store.soul_map_io import read_blob_checked

    checked = read_blob_checked(pred_path)
    if checked.kind in ("unreadable", "transient"):
        return {
            "ok": False,
            "healed": False,
            "reason": "ledger_unreadable",
            "error": checked.error or checked.kind,
        }

    daily = _daily_pick_today(picks_path)
    action = str(daily.get("action") or "").upper()
    if action in ("HOLD", "NONE", "") or not daily.get("has_pick"):
        return {"ok": True, "healed": False, "reason": "no_published_long"}

    netuid = daily.get("pick_netuid")
    if netuid is None:
        return {"ok": False, "healed": False, "reason": "missing_netuid"}
    if checked.kind == "loaded" and isinstance(checked.blob, dict):
        pred_data: Dict[str, Any] = checked.blob
    else:
        pred_data = {"predictions": [], "resolved": [], "stats": {}}

    if _day_ledger_present(netuid, pred_data):
        return {"ok": True, "healed": False, "reason": "ledger_present", "netuid": netuid}

    today_rec = _today_record(picks_path)
    stored_pick = today_rec.get("pick") if isinstance(today_rec, dict) else None
    if not isinstance(stored_pick, dict):
        return {"ok": False, "healed": False, "reason": "missing_pick_payload", "netuid": netuid}

    subnet_row = _subnet_row_for_heal(stored_pick, netuid)
    if not subnet_row:
        return {"ok": False, "healed": False, "reason": "no_reference_price", "netuid": netuid}

    if dry_run:
        return {
            "ok": True,
            "healed": False,
            "dry_run": True,
            "would_record": netuid,
            "reference_price": subnet_row.get("price"),
        }

    from internal.learning.prediction_loop import record_pick
    from internal.learning.predictions_store import PredictionsLedgerUnreadable

    market_context = today_rec.get("market_context") if isinstance(today_rec, dict) else {}
    try:
        stored = record_pick(
            stored_pick,
            subnet_row,
            horizon_type="day",
            market_context=market_context if isinstance(market_context, dict) else {},
            predictions_path=pred_path,
        )
    except PredictionsLedgerUnreadable as exc:
        return {
            "ok": False,
            "healed": False,
            "reason": "ledger_unreadable",
            "error": str(exc),
        }
    if stored.kind == "committed":
        logger.info("ledger heal: backfilled day row for SN%s", netuid)
        return {
            "ok": True,
            "healed": True,
            "netuid": netuid,
            "prediction_id": stored.prediction.get("id"),
        }

    if stored.kind == "indeterminate":
        return {"ok": False, "healed": False, "reason": "record_indeterminate"}

    if _day_ledger_present(netuid, predictions_path=pred_path):
        return {"ok": True, "healed": False, "reason": "duplicate_skipped", "netuid": netuid}

    return {"ok": False, "healed": False, "reason": "record_failed", "netuid": netuid}


def _archive_digest(path: str) -> str:
    with open(path, "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()


def _sync_directory(path: str) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _publish_epoch_archive(dest_dir: str, receipt: Dict[str, Any]) -> str:
    final = os.path.join(dest_dir, receipt["archive_name"])
    stage = os.path.join(dest_dir, f".staging-{receipt['reset_request_id']}.json")
    with open(os.path.join(dest_dir, ".publish.lock"), "a+", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        if os.path.exists(final):
            if _archive_digest(final) != receipt["archive_sha256"]:
                raise ValueError("archive_hash_mismatch")
            if os.path.exists(stage):
                if _archive_digest(stage) != receipt["archive_sha256"]:
                    raise ValueError("archive_hash_mismatch")
                os.unlink(stage)
        else:
            if not os.path.exists(stage):
                raise ValueError("archive_missing")
            if _archive_digest(stage) != receipt["archive_sha256"]:
                raise ValueError("archive_hash_mismatch")
            os.replace(stage, final)
            _sync_directory(dest_dir)
        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
    return final


def _remove_old_uncommitted_stages(dest_dir: str, history: List[Dict[str, Any]]) -> None:
    recorded = {str(item.get("reset_request_id")) for item in history}
    for name in os.listdir(dest_dir):
        if not name.startswith(".staging-") or not name.endswith(".json"):
            continue
        stage_id = name[len(".staging-"):-len(".json")]
        path = os.path.join(dest_dir, name)
        if stage_id not in recorded and time.time() - os.path.getmtime(path) > 600:
            os.unlink(path)


def reconcile_epoch_archives(*, predictions_path: Optional[str] = None, archive_dir: Optional[str] = None) -> Dict[str, Any]:
    src, dest_dir = predictions_path or predictions_store.PREDICTIONS_PATH, archive_dir or ARCHIVE_DIR
    os.makedirs(dest_dir, exist_ok=True)
    try:
        with predictions_store.locked_predictions_file(path=src):
            data = predictions_store.load_predictions(path=src, fail_closed=True)
            history = data.get("epoch_history") or []
            _remove_old_uncommitted_stages(dest_dir, history)
            for receipt in history:
                _publish_epoch_archive(dest_dir, receipt)
    except predictions_store.FileLockTimeout:
        return {"ok": False, "reason": "lock_timeout"}
    except (OSError, ValueError, KeyError, predictions_store.PredictionsLedgerUnreadable) as exc:
        return {"ok": False, "reason": str(exc)}
    return {"ok": True}


def archive_predictions_epoch(
    *,
    reset_request_id: str,
    predictions_path: Optional[str] = None,
    archive_dir: Optional[str] = None,
    re_heal_daily: bool = True,
) -> Dict[str, Any]:
    """Archive predictions.json and start a fresh epoch; re-heal today's LONG if possible."""
    src = predictions_path or predictions_store.PREDICTIONS_PATH
    dest_dir = archive_dir or ARCHIVE_DIR
    os.makedirs(dest_dir, exist_ok=True)
    try:
        request_id = str(uuid.UUID(reset_request_id))
    except (ValueError, TypeError, AttributeError):
        return {"ok": False, "reason": "invalid_reset_request_id"}
    preserve_pending = os.environ.get("PREDICTIONS_ARCHIVE_PRESERVE_PENDING", "1") != "0"
    selected: Dict[str, Any] = {}
    retry = False

    def clear_epoch(fresh, raw):
        nonlocal retry
        history = list(fresh.get("epoch_history") or [])
        _remove_old_uncommitted_stages(dest_dir, history)
        existing = next((entry for entry in history if entry.get("reset_request_id") == request_id), None)
        if existing:
            selected.update(existing)
            retry = True
            return fresh, [], []
        raw = raw or json.dumps(fresh, sort_keys=True).encode()
        sha = hashlib.sha256(raw).hexdigest()
        stamp = _utcnow().strftime("pre-epoch-%Y-%m-%dT%H%M%SZ")
        name = f"{stamp}-{request_id[:8]}.json"
        from internal.accuracy_lift.measure import ARCHIVE_NAME

        if not ARCHIVE_NAME.fullmatch(name):
            raise ValueError("invalid_archive_name")
        final = os.path.join(dest_dir, name)
        if os.path.exists(final) and _archive_digest(final) != sha:
            raise ValueError("archive_hash_mismatch")
        stage = os.path.join(dest_dir, f".staging-{request_id}.json")
        if os.path.exists(stage) and _archive_digest(stage) != sha:
            raise ValueError("archive_stage_conflict")
        if not os.path.exists(stage):
            with open(stage, "xb") as handle:
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
            _sync_directory(dest_dir)
        selected.update({
            "reset_request_id": request_id, "archive_name": name,
            "archive_sha256": sha, "reset_at": _utcnow().isoformat(),
        })
        pending = [row for row in fresh["predictions"] if row.get("status", "pending") in (None, "pending")]
        pending = pending if preserve_pending else []
        empty = {
            "predictions": pending, "resolved": [], "epoch_history": history + [dict(selected)],
            "stats": {"correct": 0, "wrong": 0, "pending": len(pending), "total": len(pending), "accuracy": 0.0},
        }
        return empty, ["epoch"], []

    try:
        persisted = predictions_store.mutate_predictions(
            clear_epoch, path=src, caller="archive_predictions_epoch", trigger="archive"
        )
    except (OSError, ValueError) as exc:
        return {"ok": False, "reason": str(exc), "heal": {"skipped": True}}
    if persisted.outcome is not predictions_store.PersistOutcome.APPLIED:
        reason = "ledger_unreadable" if persisted.reason in (
            predictions_store.PersistReason.UNREADABLE, predictions_store.PersistReason.SCHEMA_INVALID,
        ) else "persist_refused"
        return {"ok": False, "reason": reason, "heal": {"skipped": True}}
    try:
        archive_path = _publish_epoch_archive(dest_dir, selected)
    except (OSError, ValueError, KeyError) as exc:
        return {"ok": False, "reason": str(exc), "heal": {"skipped": True}}

    if retry:
        return {"ok": True, "archive_path": archive_path, "idempotent_retry": True, "heal": {"skipped": True}}

    heal_summary: Dict[str, Any] = {"skipped": not re_heal_daily}
    if re_heal_daily:
        heal_summary = heal_daily_pick_ledger(dry_run=False, predictions_path=src)

    if re_heal_daily and not heal_summary.get("healed"):
        # ponytail: never leave LONG without ledger — downgrade to honest HOLD.
        downgraded = _downgrade_today_to_hold(
            reason="Epoch reset — ledger backfill failed; no gradeable row",
        )
        heal_summary["downgraded_daily_pick"] = downgraded

    return {
        "ok": True,
        "archive_path": archive_path,
        "heal": heal_summary,
    }


def _downgrade_today_to_hold(*, reason: str, daily_picks_path: Optional[str] = None) -> bool:
    picks_path = daily_picks_path or DAILY_PICKS_PATH
    today = _utcnow().date().isoformat()
    from internal.council.daily_pick_engine import _locked_daily_picks

    with _locked_daily_picks(picks_path):
        try:
            with open(picks_path, "r", encoding="utf-8") as handle:
                records = json.load(handle)
        except Exception:
            return False
        if not isinstance(records, list):
            return False
        changed = False
        out: List[Dict[str, Any]] = []
        for rec in records:
            if isinstance(rec, dict) and rec.get("date") == today:
                rec = dict(rec)
                rec["action"] = "HOLD"
                rec["pick"] = None
                rec["reason"] = reason
                rec["epoch_reset_note"] = True
                changed = True
            out.append(rec)
        if not changed:
            return False
        tmp = picks_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(out, handle, indent=2)
        os.replace(tmp, picks_path)
        return True
