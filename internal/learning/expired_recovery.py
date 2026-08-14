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
from datetime import datetime, timezone
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

_RETIRED = frozenset({"expired", "ungradeable"})
_MAX_RECOVER = 20


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def recover_expired_predictions(
    *,
    dry_run: bool = False,
    max_rows: int = _MAX_RECOVER,
) -> Dict[str, Any]:
    """Re-resolve retired rows whose price may now be available. Idempotent."""
    from internal.learning.predictions_store import load_predictions, save_predictions, update_stats
    from internal.council.price_reference import price_at_resolve_at
    from internal.council import resolver
    from internal.council.grading import compute_actual_pct, grade_prediction

    data = load_predictions()
    resolved = data.get("resolved", []) or []
    recovered, skipped = 0, 0
    details: List[Dict[str, Any]] = []

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

        expert, _ = resolver._stamp_and_nudge_expert(row, correct=bool(correct))
        resolver._ensure_subnet_snapshot(row)
        if not resolver._skip_council_learning(row):
            resolver._nudge_impact_strength(row, bool(correct))
        resolver.atomic_finalize_resolution(
            row,
            actual_pct=actual_pct,
            outcome=new_outcome,
            correct=bool(correct),
            resolved_price=price,
            resolved_at=resolve_at.isoformat().replace("+00:00", "Z"),
            price_meta=meta,
        )
        if not resolver._skip_council_learning(row):
            resolver._record_scenario_outcome(
                row, actual_pct, new_outcome, bool(correct), expert
            )
            resolver._nudge_signal_weights(row, bool(correct))
        else:
            try:
                from internal.learning.pump_calibration import maybe_adapt_after_resolve

                maybe_adapt_after_resolve()
            except Exception:
                logger.exception("expired recovery pump calibration failed")
        row["recovered_at"] = _utcnow_iso()
        row["recovery"] = {"from": outcome, "price_source": meta.get("price_source")}
        recovered += 1

    if not dry_run and recovered:
        update_stats(data)
        save_predictions(data)
        logger.info("expired recovery: recovered=%s skipped=%s", recovered, skipped)

    return {
        "ok": True,
        "dry_run": dry_run,
        "recovered": recovered,
        "skipped": skipped,
        "details": details[:10],
    }
