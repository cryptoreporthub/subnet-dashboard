"""Score store: record validation, atomic file writes, budget ordering, coverage states."""

from __future__ import annotations

import os
import random
from datetime import datetime, timedelta, timezone

import pytest

from internal.council import score_store as ss
from internal.council.score_store import ScoreRecord, ScoreStore, coverage, select_for_budget

NOW = datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)


def _ok(netuid: int, age_seconds: float, horizon: str = "day") -> ScoreRecord:
    return ScoreRecord(
        netuid=netuid,
        horizon=horizon,
        score=0.5,
        components={"flow": 0.25},
        scored_at=NOW - timedelta(seconds=age_seconds),
        inputs_fingerprint=f"fp-{netuid}",
        status="ok",
    )


def _keyed(*records: ScoreRecord) -> dict:
    return {ss.key_of(r): r for r in records}


def test_score_record_rejects_illegal_states():
    base = dict(netuid=1, horizon="day", components={}, scored_at=NOW, inputs_fingerprint="x")
    with pytest.raises(ValueError):
        ScoreRecord(score=None, status="ok", **base)
    with pytest.raises(ValueError):
        ScoreRecord(score=None, status="failed", reason=None, **base)
    with pytest.raises(ValueError):
        ScoreRecord(score=None, status="excluded", reason="", **base)
    with pytest.raises(ValueError):
        ScoreRecord(score=0.1, status="maybe", **base)
    with pytest.raises(ValueError):
        ScoreRecord(score=0.1, status="ok", **{**base, "horizon": "week"})
    with pytest.raises(ValueError):
        ScoreRecord(score=0.1, status="ok", **{**base, "scored_at": datetime(2026, 1, 1)})


def test_budget_orders_never_scored_before_oldest():
    membership = [1, 2, 3, 4]
    records = _keyed(
        _ok(1, age_seconds=3600),
        _ok(2, age_seconds=3 * 3600),
        _ok(4, age_seconds=2 * 3600),
    )
    assert select_for_budget(membership, records, NOW, 1000, 10) == [3, 2, 4, 1]


def test_budget_cutoff_is_inclusive_and_does_not_skip_ahead():
    membership = [1, 2, 3, 4]
    records = _keyed(
        _ok(1, age_seconds=3600),
        _ok(2, age_seconds=3 * 3600),
        _ok(4, age_seconds=2 * 3600),
    )
    assert select_for_budget(membership, records, NOW, 30, 10) == [3, 2, 4]
    assert select_for_budget(membership, records, NOW, 29.9, 10) == [3, 2]
    assert select_for_budget(membership, records, NOW, 0, 10) == []


def test_budget_rejects_non_positive_estimate():
    with pytest.raises(ValueError):
        select_for_budget([1], {}, NOW, 100, 0)


def test_budget_ignores_outside_membership_and_other_horizon():
    # netuid 1 is scored on day only, netuid 2 on hour only, 99 is outside membership.
    records = _keyed(_ok(1, 100), _ok(2, 100, horizon="hour"), _ok(99, 100))
    assert select_for_budget([1, 2], records, NOW, 1000, 10) == [2, 1]
    assert select_for_budget([1, 2], records, NOW, 1000, 10, horizon="hour") == [1, 2]


def test_budget_output_is_deterministic_under_input_order():
    membership = list(range(1, 30))
    records = _keyed(*[_ok(n, age_seconds=(n * 37) % 11 * 60) for n in range(1, 30, 2)])
    expected = select_for_budget(membership, records, NOW, 400, 10)
    rng = random.Random(7)
    for _ in range(20):
        shuffled_members = membership[:]
        rng.shuffle(shuffled_members)
        items = list(records.items())
        rng.shuffle(items)
        assert select_for_budget(shuffled_members, dict(items), NOW, 400, 10) == expected


def test_coverage_fractions_and_states():
    membership = [1, 2, 3, 4]
    records = _keyed(
        _ok(1, age_seconds=60),  # fresh
        _ok(2, age_seconds=10 * 3600),  # stale
        ScoreRecord(3, "day", None, {}, NOW, "fp", "failed", reason="HTTP 503"),
    )
    counts = coverage(membership, records, NOW, fresh_within_seconds=3600)
    assert (counts.fresh, counts.stale, counts.never, counts.failed, counts.excluded) == (
        1,
        1,
        1,
        1,
        0,
    )
    assert counts.membership == 4
    assert counts.fraction == 0.25


def test_coverage_excluded_and_failed_states_carry_reason():
    membership = [1, 2]
    records = _keyed(
        ScoreRecord(1, "day", None, {}, NOW, "fp", "excluded", reason="no volume"),
        ScoreRecord(2, "day", None, {}, NOW, "fp", "failed", reason="timeout"),
    )
    counts = coverage(membership, records, NOW, fresh_within_seconds=3600)
    assert counts.excluded == 1
    assert counts.failed == 1
    assert counts.fresh == 0
    assert counts.fraction == 0.0


def test_coverage_failed_attempt_overrides_older_success():
    records = _keyed(
        _ok(1, age_seconds=60),
        ScoreRecord(1, "day", None, {}, NOW, "fp", "failed", reason="timeout"),
    )
    counts = coverage([1], records, NOW, fresh_within_seconds=3600)
    assert counts.failed == 1
    assert counts.fresh == 0


def test_coverage_denominator_is_never_clipped():
    membership = list(range(1, 129))
    records = _keyed(
        *[_ok(n, age_seconds=60) for n in range(1, 41)],
        *[_ok(n, age_seconds=60) for n in range(500, 520)],  # outside membership
    )
    counts = coverage(membership, records, NOW, fresh_within_seconds=3600)
    assert counts.membership == 128
    assert counts.fresh == 40
    assert counts.never == 88
    assert counts.fraction == 40 / 128
    assert counts.fresh + counts.stale + counts.never + counts.failed + counts.excluded == 128


def test_coverage_freshness_boundary_and_empty_membership():
    records = _keyed(_ok(1, age_seconds=3600), _ok(2, age_seconds=3601))
    counts = coverage([1, 2], records, NOW, fresh_within_seconds=3600)
    assert (counts.fresh, counts.stale) == (1, 1)
    empty = coverage([], records, NOW, fresh_within_seconds=3600)
    assert empty.membership == 0
    assert empty.fraction == 0.0


def test_duplicate_membership_is_rejected():
    with pytest.raises(ValueError):
        coverage([1, 1], {}, NOW, fresh_within_seconds=3600)
    with pytest.raises(ValueError):
        select_for_budget([1, 1], {}, NOW, 100, 10)


def test_round_trip_preserves_records(tmp_path):
    path = str(tmp_path / "score_store.json")
    originals = [
        _ok(7, age_seconds=120),
        ScoreRecord(8, "hour", None, {}, NOW, "fp8", "excluded", reason="no price"),
        ScoreRecord(9, "day", None, {"x": 0.1}, NOW - timedelta(hours=2), "fp9", "failed", "boom"),
    ]
    ScoreStore(path).put_many(originals)
    loaded = ScoreStore(path).load()
    assert loaded == _keyed(*originals)


def test_missing_and_corrupt_files_load_empty(tmp_path):
    path = str(tmp_path / "score_store.json")
    assert ScoreStore(path).load() == {}
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("{not json")
    assert ScoreStore(path).load() == {}


def test_atomic_write_crash_leaves_previous_file_intact(tmp_path, monkeypatch):
    path = str(tmp_path / "score_store.json")
    store = ScoreStore(path)
    store.put_many([_ok(1, age_seconds=60)])
    with open(path, "rb") as handle:
        before = handle.read()

    def _crash(src, dst):
        raise OSError("simulated crash during replace")

    monkeypatch.setattr(ss.os, "replace", _crash)
    with pytest.raises(OSError):
        store.put_many([_ok(2, age_seconds=60)])
    monkeypatch.undo()

    with open(path, "rb") as handle:
        assert handle.read() == before
    assert sorted(os.listdir(tmp_path)) == ["score_store.json"]
    assert set(ScoreStore(path).load()) == {(1, "day")}


def test_put_many_replaces_by_key(tmp_path):
    path = str(tmp_path / "score_store.json")
    store = ScoreStore(path)
    store.put_many([_ok(1, age_seconds=600)])
    store.put_many([_ok(1, age_seconds=5)])
    loaded = store.load()
    assert len(loaded) == 1
    assert loaded[(1, "day")].scored_at == NOW - timedelta(seconds=5)
