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
            True,
            None,
            None,
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


def _ledger_failure_scheduler(tmp_path, monkeypatch):
    import json
    import os
    from internal.council import resolver
    from internal.learning import predictions_store

    ledger = tmp_path / "predictions.json"
    ledger.write_text(json.dumps({
        "predictions": [{"id": "old", "netuid": 1, "status": "pending", "horizon_type": "hour"}],
        "resolved": [], "stats": {},
    }))
    soul = tmp_path / "soul_map.json"
    soul.write_text("{}")
    monkeypatch.setattr(predictions_store, "PREDICTIONS_PATH", str(ledger))
    monkeypatch.setattr(resolver, "PREDICTIONS_PATH", str(ledger))
    monkeypatch.setattr(
        "internal.learning.ledger_heal.DAILY_PICKS_PATH", str(tmp_path / "daily.json")
    )
    monkeypatch.setattr(
        "internal.calibration.scheduler.maybe_trigger_auto_retrain",
        lambda **_kw: {"triggered": False},
    )
    real_replace = os.replace

    def replace(src, dst):
        if str(dst) == str(ledger):
            raise OSError("injected ledger write failure")
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", replace)
    sched = resolver_scheduler.PredictionResolverScheduler(
        soul_map_path=str(soul), refresh_minutes=15, subnet_provider=lambda: [],
    )
    sched._first_tick_pending = False
    monkeypatch.setattr(
        sched, "_resolve_with_timing",
        lambda *_args: {"resolved_now": [], "expired_now": [], "stats": {}},
    )
    monkeypatch.setattr(sched, "_schedule_next", lambda *_a, **_kw: None)
    return sched, ledger, soul


def test_run_once_ledger_failure_not_hidden_by_summary(tmp_path, monkeypatch):
    import json

    sched, ledger, soul = _ledger_failure_scheduler(tmp_path, monkeypatch)
    before = ledger.read_bytes()
    result = sched.run_once()
    assert result["ok"] is False
    assert result.get("ledger_persist_outcome") == "failed"
    assert result.get("summary_persist_outcome") == "applied"
    assert result.get("error")
    assert sched._last_run_error == result["error"]
    assert sched._consecutive_failures == 1
    assert sched._backoff_minutes > sched.refresh_minutes
    assert ledger.read_bytes() == before
    assert json.loads(soul.read_text())["prediction_resolver_scheduler"]["last_cycle"]["error"]


def test_run_once_summary_failure_keeps_ledger_error(tmp_path, monkeypatch):
    sched, _ledger, _soul = _ledger_failure_scheduler(tmp_path, monkeypatch)
    monkeypatch.setattr(
        sched, "_persist_cycle_summary",
        lambda *_a, **_kw: resolver_scheduler.PersistResult(
            outcome=WriteOutcome.REPLACE_FAILED, detail="summary failure",
        ),
    )
    result = sched.run_once()
    assert result["ok"] is False
    assert "ledger" in result["error"]
    assert result.get("ledger_persist_outcome") == "failed"
    assert result.get("summary_persist_outcome") == "replace_failed"


def test_run_once_abandoned_cycle_is_skip_not_success(tmp_path, monkeypatch):
    sched, _ledger, _soul = _ledger_failure_scheduler(tmp_path, monkeypatch)
    calls = {"success": 0, "skip": 0}
    retrains = []
    monkeypatch.setattr(
        "internal.calibration.scheduler.maybe_trigger_auto_retrain",
        lambda **_kw: retrains.append(True),
    )
    monkeypatch.setattr(
        sched.liveness, "record_success",
        lambda **_kw: calls.__setitem__("success", calls["success"] + 1),
    )
    monkeypatch.setattr(
        sched.liveness, "record_skip",
        lambda **_kw: calls.__setitem__("skip", calls["skip"] + 1),
    )

    def abandon(_subnets, timing):
        timing.mark_abandoned()
        return {"resolved_now": [], "expired_now": [], "stats": {}}

    monkeypatch.setattr(sched, "_resolve_with_timing", abandon)
    result = sched.run_once()
    assert result["ok"] is False
    assert result.get("skipped") == "cycle_abandoned"
    assert calls == {"success": 0, "skip": 1}
    assert retrains == []


def test_run_once_revoked_persist_is_skip_not_failure(tmp_path, monkeypatch):
    from internal.council import resolver

    sched, ledger, _soul = _ledger_failure_scheduler(tmp_path, monkeypatch)
    before = ledger.read_bytes()
    monkeypatch.setattr(resolver, "_cycle_writes_revoked_safe", lambda: True)
    result = sched.run_once()
    assert result["ok"] is False
    assert result.get("skipped") == "abandoned_cycle_persist"
    assert result.get("error") is None
    assert result.get("ledger_persist_outcome") == "skipped_abandoned"
    assert sched._consecutive_failures == 0
    assert ledger.read_bytes() == before


def test_declined_summary_is_success_for_applied_ledger():
    sched = _sched()
    result = _fresh_cycle()
    result["ledger_persist_outcome"] = "applied"
    sched._apply_persist_honesty(
        result, resolver_scheduler.PersistResult(outcome=WriteOutcome.DECLINED)
    )
    assert result["ok"] is True
    assert result.get("skipped") is None


@pytest.mark.parametrize(
    "ledger,summary,skipped,expected",
    [
        ("applied", "applied", None, True),
        ("applied", "declined", None, True),
        ("failed", "applied", None, False),
        ("refused", "applied", None, False),
        ("skipped_abandoned", "applied", "cycle_abandoned", False),
        ("applied", "replace_failed", None, False),
        ("applied", "applied", "cycle_abandoned", False),
    ],
)
def test_cycle_ok_requires_successful_ledger_and_summary(ledger, summary, skipped, expected):
    result = {
        "ledger_persist_outcome": ledger,
        "summary_persist_outcome": summary,
        "skipped": skipped,
        "error": None,
    }
    assert resolver_scheduler._cycle_ok(result) is expected
