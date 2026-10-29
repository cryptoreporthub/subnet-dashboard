"""complete_snapshot_payload keeps an explicitly empty day list instead of substituting the defaults (#1484 Ditto r15)."""

from __future__ import annotations

from tests.score_snapshot_testutil import complete_snapshot_payload, complete_snapshot_rows


def test_explicit_empty_day_rows_are_preserved():
    snap = complete_snapshot_payload([])
    assert snap["day"] == []
    assert snap["hour"] == []


def test_omitted_day_rows_still_get_the_default_rows():
    snap = complete_snapshot_payload()
    assert snap["day"] == complete_snapshot_rows()
