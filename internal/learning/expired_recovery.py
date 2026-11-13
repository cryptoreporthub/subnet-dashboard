"""Recover expired/ungradeable predictions that can now be graded.

When predictions resolve while the price cache has no candle window (feed
outage, cold cache), resolver retires them as "expired"/"ungradeable" even
though the price may be recoverable later. With CALIBRATION_HYDRATE_ON_MISS
enabled, price_at_resolve_at now hydrates cold caches, so a recovery sweep can
re-run grading for rows that retired for data reasons — turning expired rows
back into graded outcomes instead of silently inflating expired_rate (this
was 90.5% on 2026-08-11, blocking the trust gate).

Runs inside the outcome snapshot scheduler tick (idempotent, small N; guarded
by hydrate memo so repeated sweeps are cheap).
"""

from __future__ import annotations

import logging
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_RETIRED = frozenset({"expired", "ungradeable"})
_MAX_RECOVER = 20


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")



def _prediction_still_open(pred_id: object, *, observation: Optional[dict] = None) -> bool:
    """True when any judge still holds an open position, or the book is unobservable."""
    if pred_id is None:
        return False
    try:
        from internal.judges.portfolios import observe_portfolios

        obs = observation if observation is not None else observe_portfolios()
        if obs.get("kind") != "readable":
            return True
        data = obs.get("data") or {}
        for name in ("oracle", "echo", "pulse"):
            judge = data.get(name) or {}
            for pos in judge.get("open_positions") or []:
                if pos.get("id") == pred_id:
                    return True
    except Exception:
        return True
    return False

def recover_expired_predictions(
    *,
    dry_run: bool = False,
    max_rows: int = _MAX_RECOVER,
) -> Dict[str, Any]:
    """Re-resolve retired rows whose price may now be available. Idempotent."""
    from internal.learning.predictions_store import (
        PersistOutcome,
        PredictionsLedgerUnreadable,
        load_predictions,
        merge_ledger_changes,
        update_stats,
    )
    from internal.council.price_reference import price_at_resolve_at
    from internal.council import resolver
    from internal.council.grading import compute_actual_pct, grade_prediction, is_price_unit_mismatch
    from internal.judges.portfolios import observe_portfolios

    recovered, skipped = 0, 0
    details: List[Dict[str, Any]] = []
    incomplete: List[Any] = []

    def _fail(reason: str, *, error: str = "", recovered: int = 0, **extra: Any) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "ok": False,
            "reason": reason,
            "error": error or reason,
            "dry_run": dry_run,
            "recovered": recovered,
            "skipped": skipped,
            "details": details[:10],
        }
        payload.update(extra)
        return payload

    try:
        data = load_predictions(fail_closed=True)
    except PredictionsLedgerUnreadable as exc:
        return _fail("ledger_unreadable", error=str(exc) or exc.kind)
    except OSError as exc:
        return _fail("ledger_unreadable", error=str(exc))

    observation = observe_portfolios()
    if not dry_run and observation.get("kind") != "readable":
        return _fail(
            "portfolio_unobservable",
            error=str(observation.get("error") or observation.get("kind") or "unobservable"),
        )

    before = deepcopy(data)
    resolved = data.get("resolved", []) or []
    recovered_rows: List[Dict[str, Any]] = []

    for row in resolved:
        if recovered >= max_rows:
            break
        if not isinstance(row, dict):
            continue
        outcome = str(row.get("outcome") or "").lower()
        if outcome not in _RETIRED:
            continue

        resolve_at_raw = row.get("resolve_at") or row.get("resolved_at") or row.get("horizon_end")
        if not resolve_at_raw:
            skipped += 1
            continue
        try:
            resolve_at = datetime.fromisoformat(str(resolve_at_raw).replace("Z", "+00:00"))
            if resolve_at.tzinfo is None:
                resolve_at = resolve_at.replace(tzinfo=timezone.utc)
            resolve_at = resolve_at.astimezone(timezone.utc)
        except Exception:
            skipped += 1
            continue

        netuid = row.get("netuid")
        if netuid is None:
            skipped += 1
            continue

        try:
            status, price, meta = price_at_resolve_at(netuid, resolve_at)
        except Exception:
            skipped += 1
            continue
        if status != "ok" or price <= 0:
            skipped += 1
            continue

        try:
            reference = float(
                row.get("reference_price")
                or (row.get("subnet_snapshot") or {}).get("price")
                or 0
            )
        except (TypeError, ValueError):
            reference = 0.0
        if reference <= 0:
            skipped += 1
            continue
        if is_price_unit_mismatch(reference, price):
            skipped += 1
            continue

        actual_pct = compute_actual_pct(reference, price)
        correct, new_outcome = grade_prediction(row, actual_pct)

        if dry_run:
            details.append({
                "netuid": netuid,
                "id": row.get("id"),
                "would_grade": new_outcome,
                "price": price,
            })
            recovered += 1
            continue

        from internal.council.capture import stamp_capture_fields

        capture = stamp_capture_fields(row, actual_pct)
        expert, _source = resolver._stamp_expert_attribution(row)
        resolver._ensure_subnet_snapshot(row)
        row["actual_pct"] = actual_pct
        row["outcome"] = new_outcome
        row["correct"] = bool(correct)
        row["status"] = "resolved"
        row["resolved_price"] = price
        row["resolved_at"] = resolve_at.isoformat().replace("+00:00", "Z")
        row["recovered_at"] = _utcnow_iso()
        row["recovery"] = {"from": outcome, "price_source": meta.get("price_source")}
        recovered_rows.append({
            "row": row,
            "actual_pct": actual_pct,
            "new_outcome": new_outcome,
            "correct": bool(correct),
            "price": price,
            "resolve_at": resolve_at,
            "meta": meta,
            "capture": capture,
            "expert": expert,
            "prior_outcome": outcome,
        })
        recovered += 1

    if not dry_run and recovered:
        try:
            update_stats(data)
            result = merge_ledger_changes(
                before, data, caller="expired_recovery", trigger="expired_recovery"
            )
        except Exception as exc:
            return _fail(
                "persist_failed",
                error=str(exc),
                incomplete_ids=incomplete or None,
            )
        if result.outcome is not PersistOutcome.APPLIED:
            reason = result.reason.value if result.reason is not None else "persist_refused"
            return _fail(
                reason,
                error=reason,
                recovered=0,
                incomplete_ids=incomplete or None,
            )
        # APPLIED means the after-image (including recovered_rows) is on disk.
        applied_rows = list(recovered_rows)
        recovered = len(applied_rows)
        try:
            for item in applied_rows:
                row = item["row"]
                if not resolver._skip_council_learning(row):
                    resolver._nudge_attributed_expert(
                        row,
                        correct=item["correct"],
                        capture=item["capture"],
                        stamped_expert=item["expert"],
                    )
                    resolver._nudge_impact_strength(row, item["correct"])
                warnings_before = list(row.get("side_effect_warnings") or [])
                resolver.atomic_finalize_resolution(
                    row,
                    actual_pct=item["actual_pct"],
                    outcome=item["new_outcome"],
                    correct=item["correct"],
                    resolved_price=item["price"],
                    resolved_at=item["resolve_at"].isoformat().replace("+00:00", "Z"),
                    price_meta=item["meta"],
                    apply_judge_nudge=False,
                )
                warnings_after = list(row.get("side_effect_warnings") or [])
                fresh_close_warning = (
                    "on_prediction_resolved" in warnings_after
                    and "on_prediction_resolved" not in warnings_before
                )
                still_open = _prediction_still_open(row.get("id"), observation=observation)
                if still_open:
                    # Re-check after close so a pre-close readable book can complete.
                    still_open = _prediction_still_open(row.get("id"))
                    if observation.get("kind") != "readable":
                        still_open = True
                if fresh_close_warning or still_open:
                    incomplete.append(row.get("id"))
                if not resolver._skip_council_learning(row):
                    resolver._record_scenario_outcome(
                        row, item["actual_pct"], item["new_outcome"], item["correct"], item["expert"]
                    )
                    resolver._nudge_signal_weights(row, item["correct"], capture=item["capture"])
                else:
                    try:
                        from internal.learning.pump_calibration import maybe_adapt_after_resolve

                        maybe_adapt_after_resolve()
                    except Exception:
                        logger.exception("expired recovery pump calibration failed")
        except Exception as exc:
            logger.exception("expired recovery post-commit effects failed")
            return _fail(
                "effects_incomplete",
                error=str(exc),
                recovered=recovered,
                incomplete_ids=incomplete or None,
            )
        logger.info("expired recovery: recovered=%s skipped=%s", recovered, skipped)

    if incomplete:
        return _fail(
            "judge_close_incomplete",
            error="judge_close_incomplete",
            recovered=recovered,
            incomplete_ids=incomplete,
        )

    return {
        "ok": True,
        "dry_run": dry_run,
        "recovered": recovered,
        "skipped": skipped,
        "details": details[:10],
    }
