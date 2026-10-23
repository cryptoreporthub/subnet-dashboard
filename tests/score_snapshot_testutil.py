"""Helpers for complete score-snapshot fixtures (PR-B)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from internal.council.scorer_identity import stamp_scorer_fields


def complete_snapshot_rows(
    netuids: Optional[List[int]] = None,
    *,
    score: float = 90.0,
) -> List[Dict[str, Any]]:
    ids = netuids or [2, 3]
    return [{"netuid": n, "total_score": score, "name": f"S{n}"} for n in ids]


def complete_snapshot_payload(
    day_rows: Optional[List[Dict[str, Any]]] = None,
    *,
    hour_rows: Optional[List[Dict[str, Any]]] = None,
    written_at: str = "2026-10-17T00:00:00Z",
) -> Dict[str, Any]:
    day = day_rows or complete_snapshot_rows()
    hour = hour_rows if hour_rows is not None else list(day)
    expected = [int(r["netuid"]) for r in day]
    return stamp_scorer_fields(
        {
            "written_at": written_at,
            "build_started_at": written_at,
            "hour": hour,
            "day": day,
            "coverage": {
                "complete": True,
                "published": True,
                "membership": {"expected_netuids": expected},
                "day": {
                    "complete": True,
                    "expected": expected,
                    "expected_count": len(expected),
                    "succeeded_count": len(expected),
                },
                "hour": {"complete": True, "hour_copied_from_day": True},
            },
        }
    )
