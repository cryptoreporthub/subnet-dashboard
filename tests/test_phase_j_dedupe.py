"""Phase J — duplicate prediction collapse."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from internal.council.deduplication import dedupe_predictions, mark_duplicates_in_resolved


def _pred(netuid: int, pct: float, minute: int) -> dict:
    created = datetime(2026, 7, 1, 12, minute, tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
    return {
        "id": f"{netuid}-{minute}",
        "netuid": netuid,
        "predicted_pct": pct,
        "created_at": created,
        "status": "pending",
    }


def test_dedupe_keeps_first_within_five_minute_window():
    rows = [_pred(5, 3.0, 0), _pred(5, 3.0, 3), _pred(5, 3.0, 6)]
    kept, dropped = dedupe_predictions(rows)
    assert len(kept) == 2
    assert len(dropped) == 1
    assert dropped[0]["status"] == "duplicate"
    assert dropped[0]["outcome"] == "duplicate"


def test_dedupe_allows_different_predicted_pct():
    rows = [_pred(5, 3.0, 0), _pred(5, 4.0, 1)]
    kept, dropped = dedupe_predictions(rows)
    assert len(kept) == 2
    assert dropped == []


def test_mark_duplicates_in_resolved_tags_second_row():
    rows = [_pred(1, 2.0, 0), _pred(1, 2.0, 2)]
    for row in rows:
        row["status"] = "resolved"
    tagged = mark_duplicates_in_resolved(rows)
    assert tagged[0].get("outcome") != "duplicate"
    assert tagged[1]["outcome"] == "duplicate"
