"""Historical replay — re-grade at true resolve_at (Phase J2 + J3)."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from internal.council.deduplication import dedupe_predictions, mark_duplicates_in_resolved
from internal.council.resolver import (
    PREDICTIONS_PATH,
    _compute_stats,
    _load_json,
    _commit_ledger_changes,
    replay_mode,
    resolve_prediction_at_horizon,
)

PORTFOLIOS_PATH = os.path.join("data", "judge_portfolios.json")


def _parse_dt(raw: Any) -> Optional[datetime]:
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _default_portfolios() -> Dict[str, Any]:
    return {}


def reset_judge_portfolios(path: str = PORTFOLIOS_PATH) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(_default_portfolios(), fh, indent=2)
    os.replace(tmp, path)


def rebuild_judge_portfolios_from_stream(
    stream: List[Dict[str, Any]],
    *,
    portfolios_path: str = PORTFOLIOS_PATH,
) -> Dict[str, Any]:
    """Rebuild open/closed judge positions from a unified prediction stream."""
    from internal.judges import portfolios as jp
    from internal.judges.tracker import on_prediction_created, on_prediction_resolved

    old_path = jp.PORTFOLIOS_PATH
    jp.PORTFOLIOS_PATH = portfolios_path
    try:
        reset_judge_portfolios(portfolios_path)
        sorted_stream = sorted(
            stream,
            key=lambda p: _parse_dt(p.get("created_at")) or datetime.min.replace(tzinfo=timezone.utc),
        )
        from internal.judges import postmortems

        for pred in sorted_stream:
            if not isinstance(pred, dict):
                continue
            status = str(pred.get("status", "pending"))
            if status in {"duplicate", "expired"} and pred.get("outcome") == "duplicate":
                continue
            if status in {"resolved", "expired", "ungradeable"}:
                actual_pct = pred.get("actual_pct")
                outcome = pred.get("outcome")
                for name in ("oracle", "echo", "pulse"):
                    jp.backfill_closed_position(
                        name, pred, actual_pct=actual_pct, outcome=outcome
                    )
                stored_correct = pred.get("correct")
                if stored_correct is None:
                    stored_correct = str(outcome or "").lower() == "hit"
                if not stored_correct and outcome not in {"expired", "ungradeable", "unknown", None}:
                    for name in ("oracle", "echo", "pulse"):
                        try:
                            postmortems.record(name, pred, actual_pct=actual_pct)
                        except Exception:
                            continue
                continue
            on_prediction_created(pred)
        return jp.all_portfolios()
    finally:
        jp.PORTFOLIOS_PATH = old_path


def replay_predictions(
    *,
    predictions_path: str = PREDICTIONS_PATH,
    portfolios_path: str = PORTFOLIOS_PATH,
    persist: bool = True,
) -> Dict[str, Any]:
    """Re-label all predictions at horizon-end prices; rebuild judge portfolios."""
    data = _load_json(
        predictions_path,
        {"predictions": [], "resolved": [], "stats": {"correct": 0, "wrong": 0, "pending": 0}},
    )
    before_stats = dict(data.get("stats") or {})
    combined = list(data.get("predictions", [])) + list(data.get("resolved", []))
    combined.sort(
        key=lambda p: _parse_dt(p.get("created_at")) or datetime.min.replace(tzinfo=timezone.utc),
    )

    with replay_mode(True):
        relabeled: List[Dict[str, Any]] = []
        for raw in combined:
            if not isinstance(raw, dict):
                continue
            pred = dict(raw)
            pred["status"] = "pending"
            for key in ("outcome", "correct", "actual_pct", "resolved_at", "resolved_price"):
                pred.pop(key, None)
            relabeled.append(resolve_prediction_at_horizon(pred))

        deduped_pending, duplicates = dedupe_predictions(
            [p for p in relabeled if p.get("status") == "pending"],
        )
        resolved_rows = [
            p for p in relabeled if p.get("status") in {"resolved", "expired", "ungradeable", "duplicate"}
        ]
        resolved_rows.extend(duplicates)
        resolved_rows = mark_duplicates_in_resolved(resolved_rows)

        pending: List[Dict[str, Any]] = deduped_pending
        resolved: List[Dict[str, Any]] = resolved_rows

        rebuild_judge_portfolios_from_stream(
            pending + resolved,
            portfolios_path=portfolios_path,
        )

        out: Dict[str, Any] = {
            "predictions": pending,
            "resolved": resolved,
            "stats": _compute_stats({"predictions": pending, "resolved": resolved}),
            "replay": {
                "before_stats": before_stats,
                "after_stats": {},
                "total_replayed": len(combined),
            },
        }
        out["replay"]["after_stats"] = dict(out["stats"])

        if persist:
            result = _commit_ledger_changes(
                data, out, path=predictions_path, caller="replay", trigger="replay"
            )
            out["persist_outcome"] = result.outcome.value
        return out


def replay_summary(before: Dict[str, Any], after: Dict[str, Any]) -> str:
    b_acc = before.get("accuracy", 0)
    a_acc = after.get("accuracy", 0)
    return (
        f"accuracy {b_acc} → {a_acc}; "
        f"correct {before.get('correct', 0)} → {after.get('correct', 0)}; "
        f"wrong {before.get('wrong', 0)} → {after.get('wrong', 0)}"
    )
