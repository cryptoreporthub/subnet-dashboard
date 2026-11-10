"""Scheduler persist honesty: every PersistResult outcome (Unit 1 #1559)."""

from __future__ import annotations

import pytest

from internal.council import resolver_scheduler
from internal.store.soul_map_io import WriteOutcome


def _fresh_cycle() -> dict:
    return {
        "ok": True,
        "resolved_now": 1,
        "expired_now": 0,
        "pending": 0,
    }


def _sched(refresh_minutes: int = 15) -> resolver_scheduler.PredictionResolverScheduler:
    return resolver_scheduler.PredictionResolverScheduler(refresh_minutes=refresh_minutes)


@pytest.mark.parametrize(
    "persist,expect_ok,expect_error,expect_skipped,expect_persist_outcome",
    [
        pytest.param(
            resolver_scheduler.PersistResult(skipped_not_owner=True),
            False,
            None,
            "persist_skipped",
            "skipped_not_owner",
            id="skipped_not_owner",
        ),
        pytest.param(
            resolver_scheduler.PersistResult(outcome=WriteOutcome.DECLINED),
            False,
            None,
            "persist_declined",
            "declined",
            id="declined",
        ),
        pytest.param(
            resolver_scheduler.PersistResult(outcome=WriteOutcome.APPLIED),
            True,
            None,
            None,
            "applied",
            id="applied",
        ),
        pytest.param(
            resolver_scheduler.PersistResult(outcome=None),
            True,
            None,
            None,
            None,
            id="none",
        ),
        pytest.param(
            resolver_scheduler.PersistResult(
                outcome=WriteOutcome.UNREADABLE_BLOB, detail="sidecar=deadbeef"
            ),
            False,
            "persist_refused:unreadable_blob sidecar=deadbeef",
            None,
            "unreadable_blob",
            id="unreadable_blob",
        ),
        pytest.param(
            resolver_scheduler.PersistResult(
                outcome=WriteOutcome.LOCK_WAIT_FAILED,
                detail="persist_lock_wait>5s",
            ),
            False,
            "persist_refused:lock_wait_failed persist_lock_wait>5s",
            None,
            "lock_wait_failed",
            id="lock_wait_failed",
        ),
        pytest.param(
            resolver_scheduler.PersistResult(
                outcome=WriteOutcome.REPLACE_FAILED, detail="OSError"
            ),
            False,
            "persist_refused:replace_failed OSError",
            None,
            "replace_failed",
            id="replace_failed",
        ),
        pytest.param(
            resolver_scheduler.PersistResult(outcome=WriteOutcome.OWNERSHIP_UNKNOWN),
            False,
            "persist_refused:ownership_unknown",
            None,
            "ownership_unknown",
            id="ownership_unknown",
        ),
        pytest.param(
            resolver_scheduler.PersistResult(
                outcome=WriteOutcome.READ_FAILED, detail="transient"
            ),
            False,
            "persist_refused:read_failed transient",
            None,
            "read_failed",
            id="read_failed",
        ),
    ],
)
def test_apply_persist_honesty_every_outcome_on_clean_cycle(
    persist,
    expect_ok,
    expect_error,
    expect_skipped,
    expect_persist_outcome,
):
    sched = _sched()
    result = _fresh_cycle()
    sched._apply_persist_honesty(result, persist)
    assert result["ok"] is expect_ok
    assert result.get("error") == expect_error
    assert result.get("skipped") == expect_skipped
    assert result.get("persist_outcome") == expect_persist_outcome


def _tick_with_persist(monkeypatch, persist, *, refresh_minutes: int = 15):
    sched = _sched(refresh_minutes=refresh_minutes)
    sched._active = True
    sched._backoff_minutes = 240
    sched._consecutive_failures = 3
    liveness_calls: dict = {"skip": [], "fail": [], "success": 0}

    monkeypatch.setattr(
        sched.liveness,
        "record_skip",
        lambda reason: liveness_calls["skip"].append(reason),
    )
    monkeypatch.setattr(
        sched.liveness,
        "record_failure",
        lambda error: liveness_calls["fail"].append(error),
    )
    monkeypatch.setattr(
        sched.liveness,
        "record_success",
        lambda **_: liveness_calls.__setitem__("success", liveness_calls["success"] + 1),
    )
    monkeypatch.setattr(sched, "_schedule_next", lambda *_a, **_k: None)
    monkeypatch.setattr(sched, "_persist_lifecycle_state", lambda: None)
    monkeypatch.setattr(sched, "_mark_first_tick", lambda _r: False)

    cycle = _fresh_cycle()
    sched._apply_persist_honesty(cycle, persist)
    monkeypatch.setattr(sched, "_run_refresh_cycle_with_timeout", lambda: cycle)
    sched._tick(sync_manual=True)
    return sched, liveness_calls, cycle


def test_tick_ownership_unknown_records_failure_flat_backoff(monkeypatch):
    sched, calls, cycle = _tick_with_persist(
        monkeypatch,
        resolver_scheduler.PersistResult(outcome=WriteOutcome.OWNERSHIP_UNKNOWN),
    )
    assert calls["success"] == 0
    assert len(calls["fail"]) == 1
    assert "ownership_unknown" in calls["fail"][0]
    assert cycle.get("persist_outcome") == "ownership_unknown"
    assert sched._backoff_minutes == 15
    assert sched._consecutive_failures == 4


def test_tick_unreadable_blob_records_failure_doubling_backoff(monkeypatch):
    sched, calls, _cycle = _tick_with_persist(
        monkeypatch,
        resolver_scheduler.PersistResult(
            outcome=WriteOutcome.UNREADABLE_BLOB, detail="sidecar=x"
        ),
    )
    assert calls["success"] == 0
    assert len(calls["fail"]) == 1
    assert "unreadable_blob" in calls["fail"][0]
    assert sched._backoff_minutes == min(15 * (2**4), sched.max_backoff_minutes)
    assert sched._consecutive_failures == 4


def test_tick_skipped_not_owner_records_skip_and_refresh_backoff(monkeypatch):
    sched, calls, cycle = _tick_with_persist(
        monkeypatch,
        resolver_scheduler.PersistResult(skipped_not_owner=True),
    )
    assert calls["skip"] == ["persist_skipped"]
    assert calls["fail"] == []
    assert calls["success"] == 0
    assert cycle.get("persist_outcome") == "skipped_not_owner"
    assert sched._backoff_minutes == 15
    assert sched._consecutive_failures == 0
