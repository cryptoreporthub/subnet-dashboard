"""Heal daily-pick → predictions.json ledger gaps (Acc-0).

When today's published LONG exists in ``daily_picks.json`` but no gradeable day
row exists in ``predictions.json`` (common after an accuracy epoch reset), this
module idempotently backfills via ``record_pick_prediction``.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from internal.learning.loop_health import _daily_pick_today, _day_ledger_present
from internal.learning.predictions_store import PREDICTIONS_PATH, load_predictions, save_predictions

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
    daily = _daily_pick_today(picks_path)
    action = str(daily.get("action") or "").upper()
    if action in ("HOLD", "NONE", "") or not daily.get("has_pick"):
        return {"ok": True, "healed": False, "reason": "no_published_long"}

    netuid = daily.get("pick_netuid")
    if netuid is None:
        return {"ok": False, "healed": False, "reason": "missing_netuid"}

    pred_data: Optional[Dict[str, Any]] = None
    if predictions_path:
        try:
            with open(predictions_path, "r", encoding="utf-8") as handle:
                pred_data = json.load(handle)
        except Exception:
            pred_data = {"predictions": [], "resolved": [], "stats": {}}
    else:
        pred_data = load_predictions()

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

    from internal.learning.prediction_loop import record_pick_prediction

    market_context = today_rec.get("market_context") if isinstance(today_rec, dict) else {}
    stored = record_pick_prediction(
        stored_pick,
        subnet_row,
        horizon_type="day",
        market_context=market_context if isinstance(market_context, dict) else {},
    )
    if stored:
        logger.info("ledger heal: backfilled day row for SN%s", netuid)
        return {
            "ok": True,
            "healed": True,
            "netuid": netuid,
            "prediction_id": stored.get("id"),
        }

    if _day_ledger_present(netuid):
        return {"ok": True, "healed": False, "reason": "duplicate_skipped", "netuid": netuid}

    return {"ok": False, "healed": False, "reason": "record_failed", "netuid": netuid}


def archive_predictions_epoch(
    *,
    predictions_path: Optional[str] = None,
    archive_dir: Optional[str] = None,
    re_heal_daily: bool = True,
) -> Dict[str, Any]:
    """Archive predictions.json and start a fresh epoch; re-heal today's LONG if possible."""
    src = predictions_path or PREDICTIONS_PATH
    dest_dir = archive_dir or ARCHIVE_DIR
    os.makedirs(dest_dir, exist_ok=True)
    stamp = _utcnow().strftime("pre-epoch-%Y-%m-%dT%H%M%SZ")
    archive_path = os.path.join(dest_dir, stamp)

    try:
        if os.path.isfile(src):
            shutil.copy2(src, archive_path)
        else:
            archive_path = None
    except Exception as exc:
        return {"ok": False, "reason": "archive_failed", "error": str(exc)}

    empty = {
        "predictions": [],
        "resolved": [],
        "stats": {"correct": 0, "wrong": 0, "pending": 0, "total": 0, "accuracy": 0.0},
        "epoch_reset_at": _utcnow().isoformat().replace("+00:00", "Z"),
    }
    save_predictions(empty)

    heal_summary: Dict[str, Any] = {"skipped": not re_heal_daily}
    if re_heal_daily:
        heal_summary = heal_daily_pick_ledger(dry_run=False)

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
