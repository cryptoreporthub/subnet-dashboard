"""Ledger for experimental combined next-up+peer calls.

Tracks a full slate (default top 5) so we can measure whether combined
beats next-up-alone / peers-alone — UI only shows one pick.

Also freezes a gradeable prediction for the *shown* pick
(pick_source=pump_combined_exp) — graded like pump_lead (+2% / 1h),
excluded from council weight learning.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

LEDGER_PATH = os.environ.get(
    "PUMP_COMBINED_LEDGER_PATH",
    os.path.join("data", "pump_combined_calls.json"),
)
CLAIM_PCT = 2.0
HORIZON_HOURS = 1
_DEDUP_MINUTES = 45
_MAX_LEDGER = 200


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


def _load() -> Dict[str, Any]:
    path = LEDGER_PATH
    if not os.path.isfile(path):
        return {"calls": [], "version": 1}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and isinstance(data.get("calls"), list):
            return data
    except Exception as exc:
        logger.debug("combined ledger load failed: %s", exc)
    return {"calls": [], "version": 1}


def _save(data: Dict[str, Any]) -> None:
    path = LEDGER_PATH
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)


def _parse_ts(raw: Any) -> Optional[datetime]:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except Exception:
        return None


def _recent_same_shown(calls: List[Dict[str, Any]], shown: int) -> bool:
    cutoff = _utcnow() - timedelta(minutes=_DEDUP_MINUTES)
    for row in reversed(calls[-20:]):
        if not isinstance(row, dict):
            continue
        if int(row.get("shown_netuid") or -1) != shown:
            continue
        ts = _parse_ts(row.get("created_at"))
        if ts and ts >= cutoff:
            return True
    return False


def _has_pending_exp(netuid: int) -> bool:
    try:
        from internal.learning.predictions_store import load_predictions

        for row in load_predictions().get("predictions") or []:
            if not isinstance(row, dict):
                continue
            if row.get("status") != "pending":
                continue
            if str(row.get("pick_source") or "").lower() != "pump_combined_exp":
                continue
            if int(row.get("netuid") or -1) == netuid:
                return True
    except Exception:
        return False
    return False


def _freeze_shown_prediction(shown: Dict[str, Any], angles: Dict[str, Any]) -> Optional[str]:
    """Gradeable experimental claim for the UI pick only."""
    try:
        nid = int(shown.get("netuid"))
    except (TypeError, ValueError):
        return None
    if nid < 1:
        return None
    price = float(shown.get("price") or 0)
    if price <= 0:
        return None
    if _has_pending_exp(nid):
        return None

    now = _utcnow()
    pred_id = uuid.uuid4().hex[:10]
    prediction: Dict[str, Any] = {
        "id": pred_id,
        "netuid": nid,
        "name": shown.get("name") or f"SN{nid}",
        "direction": "up",
        "predicted_pct": CLAIM_PCT,
        "horizon_hours": HORIZON_HOURS,
        "horizon_type": "pump_combined_exp",
        "reference_price": price,
        "created_at": _iso(now),
        "resolve_at": _iso(now + timedelta(hours=HORIZON_HOURS)),
        "status": "pending",
        "pick_source": "pump_combined_exp",
        "pump_phase": shown.get("phase"),
        "pump_badge": "COMBINED EXP",
        "pump_claim": "COMBINED_EXP",
        "composite_score": shown.get("score"),
        "timing_pts": shown.get("timing_pts"),
        "peer_pts": shown.get("peer_pts"),
        "combined_pts": shown.get("combined_pts"),
        "focus_netuid": angles.get("focus_netuid"),
        "weights": angles.get("weights"),
        "experimental": True,
        "statement": (
            f"experimental combined +{CLAIM_PCT:.0f}% within 1h "
            f"(timing {shown.get('timing_pts')} · peer {shown.get('peer_pts')})"
        ),
    }
    try:
        from internal.learning.predictions_store import append_prediction

        if append_prediction(prediction):
            return pred_id
    except Exception as exc:
        logger.debug("combined exp prediction skip: %s", exc)
    return None


def maybe_record_combined_call(angles: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Append slate snapshot when we have a combined pick (deduped)."""
    shown = angles.get("combined")
    tracked = angles.get("tracked") or []
    if not isinstance(shown, dict) or not tracked:
        return None
    try:
        shown_id = int(shown.get("netuid"))
    except (TypeError, ValueError):
        return None

    data = _load()
    calls: List[Dict[str, Any]] = list(data.get("calls") or [])
    if _recent_same_shown(calls, shown_id):
        return None

    next_up = angles.get("next_up") or []
    peers = (angles.get("peers") or {}).get("matches") or []
    pred_id = _freeze_shown_prediction(shown, angles)

    call = {
        "id": uuid.uuid4().hex[:10],
        "created_at": _iso(_utcnow()),
        "experimental": True,
        "focus_netuid": angles.get("focus_netuid"),
        "shown_netuid": shown_id,
        "shown": shown,
        "tracked": tracked[:5],
        "next_up_top": next_up[0] if next_up else None,
        "peer_top": peers[0] if peers else None,
        "weights": angles.get("weights"),
        "prediction_id": pred_id,
        "claim_pct": CLAIM_PCT,
        "horizon_hours": HORIZON_HOURS,
        # filled later by graders / offline compare
        "outcomes": None,
    }
    calls.append(call)
    data["calls"] = calls[-_MAX_LEDGER:]
    data["updated_at"] = call["created_at"]
    try:
        _save(data)
    except Exception as exc:
        logger.warning("combined ledger save failed: %s", exc)
        return None
    logger.info(
        "combined call: show SN%s track=%s pred=%s",
        shown_id,
        len(call["tracked"]),
        pred_id,
    )
    return call


def ledger_stats() -> Dict[str, Any]:
    """Lightweight effectiveness counters (outcomes may be sparse until graded)."""
    data = _load()
    calls = [c for c in (data.get("calls") or []) if isinstance(c, dict)]
    graded = [c for c in calls if isinstance(c.get("outcomes"), dict)]
    return {
        "calls": len(calls),
        "graded": len(graded),
        "experimental": True,
        "path": LEDGER_PATH,
    }


EFFECTIVENESS_PATH = os.environ.get(
    "COMBINED_ANGLES_EFFECTIVENESS_PATH",
    os.path.join("data", "learning_outcomes", "combined_angles_effectiveness.json"),
)
_MIN_TUNE_N = 20
_SKIP_OUTCOMES = frozenset({"duplicate", "expired", "ungradeable"})


def _bucket_hits(hits: List[bool]) -> Dict[str, Any]:
    n = len(hits)
    h = sum(1 for x in hits if x)
    rate = round(h / n, 4) if n else None
    return {"n": n, "hits": h, "hit_rate": rate}


def _resolved_index() -> Dict[str, Dict[str, Any]]:
    try:
        from internal.learning.predictions_store import load_predictions

        rows = load_predictions().get("resolved") or []
    except Exception:
        return {}
    out: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        pid = str(row.get("id") or "")
        if pid:
            out[pid] = row
    return out


def _gradeable_pump_row(row: Dict[str, Any]) -> bool:
    from internal.council.grading import is_pump_desk_claim

    if not is_pump_desk_claim(row):
        return False
    if row.get("outcome") in _SKIP_OUTCOMES:
        return False
    if row.get("sample_quality") == "reject":
        return False
    if row.get("correct") is None and row.get("actual_pct") is None:
        return False
    return True


def _pick_source_buckets(resolved: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    from internal.council.grading import is_pump_combined_exp, is_pump_lead

    combined_hits: List[bool] = []
    lead_hits: List[bool] = []
    for row in resolved.values():
        if not _gradeable_pump_row(row):
            continue
        hit = row.get("correct") is True
        if is_pump_combined_exp(row):
            combined_hits.append(hit)
        elif is_pump_lead(row):
            lead_hits.append(hit)
    return {
        "pump_combined_exp": _bucket_hits(combined_hits),
        "pump_lead": _bucket_hits(lead_hits),
    }


def _grade_candidate_at_call(
    candidate: Optional[Dict[str, Any]],
    *,
    created_at: Optional[datetime],
    claim_pct: float = CLAIM_PCT,
) -> Optional[bool]:
    """Grade +claim_pct within HORIZON_HOURS for a slate candidate (next_up / peer)."""
    if not isinstance(candidate, dict) or not created_at:
        return None
    try:
        netuid = int(candidate.get("netuid"))
        ref = float(candidate.get("price") or 0)
    except (TypeError, ValueError):
        return None
    if netuid < 1 or ref <= 0:
        return None
    resolve_at = created_at + timedelta(hours=HORIZON_HOURS)
    try:
        from internal.council.grading import (
            compute_actual_pct,
            is_price_unit_mismatch,
            pump_lead_hit,
        )
        from internal.council.price_reference import price_at_resolve_at

        status, resolved_price, _meta = price_at_resolve_at(netuid, resolve_at)
        if status != "ok" or resolved_price <= 0:
            return None
        if is_price_unit_mismatch(ref, resolved_price):
            return None
        actual_pct = compute_actual_pct(ref, resolved_price)
        pred = {"predicted_pct": claim_pct, "pump_claim": "COMBINED_EXP", "pump_badge": "COMBINED EXP"}
        return pump_lead_hit(pred, actual_pct)
    except Exception:
        return None


def _call_outcomes(
    call: Dict[str, Any],
    resolved: Dict[str, Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Per-call angle outcomes — stored dict wins; else backfill from predictions/candles."""
    stored = call.get("outcomes")
    if isinstance(stored, dict) and any(
        isinstance(stored.get(k), dict) and stored[k].get("hit") is not None
        for k in ("combined", "next_up", "peer")
    ):
        return stored

    created = _parse_ts(call.get("created_at"))
    claim = float(call.get("claim_pct") or CLAIM_PCT)
    out: Dict[str, Any] = {}

    pid = str(call.get("prediction_id") or "")
    pred = resolved.get(pid) if pid else None
    if pred and _gradeable_pump_row(pred):
        out["combined"] = {"hit": pred.get("correct") is True, "source": "prediction"}

    nu_hit = _grade_candidate_at_call(call.get("next_up_top"), created_at=created, claim_pct=claim)
    if nu_hit is not None:
        out["next_up"] = {"hit": nu_hit, "source": "candle"}

    peer_hit = _grade_candidate_at_call(call.get("peer_top"), created_at=created, claim_pct=claim)
    if peer_hit is not None:
        out["peer"] = {"hit": peer_hit, "source": "candle"}

    return out or None


def build_effectiveness_summary() -> Dict[str, Any]:
    """Combined vs next_up vs peer hit rates + pick_source buckets for ops evidence."""
    data = _load()
    calls = [c for c in (data.get("calls") or []) if isinstance(c, dict)]
    resolved = _resolved_index()

    combined_hits: List[bool] = []
    next_up_hits: List[bool] = []
    peer_hits: List[bool] = []
    graded_calls = 0

    for call in calls:
        outcomes = _call_outcomes(call, resolved)
        if not outcomes:
            continue
        graded_calls += 1
        for key, bucket in (
            ("combined", combined_hits),
            ("next_up", next_up_hits),
            ("peer", peer_hits),
        ):
            row = outcomes.get(key)
            if isinstance(row, dict) and row.get("hit") is not None:
                bucket.append(bool(row["hit"]))

    pick_sources = _pick_source_buckets(resolved)
    combined_n = pick_sources["pump_combined_exp"]["n"]
    graded_predictions = sum(row["n"] for row in pick_sources.values())

    return {
        "generated_at": _iso(_utcnow()),
        "experimental": True,
        "ledger": {
            "calls": len(calls),
            "graded_calls": graded_calls,
            "path": LEDGER_PATH,
        },
        "angles": {
            "combined": _bucket_hits(combined_hits),
            "next_up": _bucket_hits(next_up_hits),
            "peer": _bucket_hits(peer_hits),
        },
        "pick_source": pick_sources,
        "gates": {
            "graded_predictions": graded_predictions,
            "tune_ready": combined_n >= _MIN_TUNE_N,
            "min_tune_n": _MIN_TUNE_N,
            "weights_locked": combined_n < _MIN_TUNE_N,
        },
        "weights": {"timing": 0.70, "peer": 0.30},
    }


def save_effectiveness_artifact(summary: Optional[Dict[str, Any]] = None) -> str:
    """Write effectiveness JSON for Ditto / GHA probes."""
    payload = summary if summary is not None else build_effectiveness_summary()
    path = EFFECTIVENESS_PATH
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    os.replace(tmp, path)
    return path
