import json
import os
import threading

import pytest

from internal.council import price_reference
from internal.council import learning_effects
from internal.learning import predictions_store, pump_calibration, pump_lead_recover


def _pump_ledger(tmp_path, monkeypatch):
    path = tmp_path / "predictions.json"
    path.write_text(json.dumps({
        "predictions": [{
            "id": "pump-1", "netuid": 1, "status": "pending",
            "resolve_at": "2026-01-01T00:00:00Z", "horizon_type": "hour",
        }],
        "resolved": [], "stats": {},
    }))
    monkeypatch.setattr(
        pump_lead_recover, "is_pump_desk_claim", lambda row: row.get("id") == "pump-1"
    )
    monkeypatch.setattr(price_reference, "_load_cache", lambda *_a, **_kw: {})
    monkeypatch.setattr(pump_lead_recover, "update_pump_horizon_outcomes", lambda *_a, **_kw: 0)
    monkeypatch.setattr(
        pump_lead_recover, "grade_pump_lead_at_resolve_candle",
        lambda row, **_kw: {
            **row, "status": "resolved", "correct": True, "outcome": "hit",
            "resolved_at": "2026-01-01T01:00:00Z",
        },
    )
    return path


def test_pump_refused_commit_does_not_calibrate(tmp_path, monkeypatch):
    path = _pump_ledger(tmp_path, monkeypatch)
    before = path.read_bytes()
    calls = []
    monkeypatch.setattr(pump_calibration, "maybe_adapt_after_resolve", lambda **_kw: calls.append(1))
    real_replace = os.replace

    def replace(src, dst):
        if str(dst) == str(path):
            raise OSError("injected ledger failure")
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", replace)
    try:
        result = pump_lead_recover.recover_overdue_pump_leads(path=str(path), hydrate=False)
    except OSError:
        result = {"ok": False}
    assert calls == []
    assert result["ok"] is False
    assert path.read_bytes() == before


def test_pump_retry_after_refused_commit_calibrates_once(tmp_path, monkeypatch):
    path = _pump_ledger(tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(pump_calibration, "maybe_adapt_after_resolve", lambda **_kw: calls.append(1))
    real_replace = os.replace

    def replace(src, dst):
        if str(dst) == str(path):
            raise OSError("injected ledger failure")
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", replace)
    try:
        pump_lead_recover.recover_overdue_pump_leads(path=str(path), hydrate=False)
    except OSError:
        pass
    monkeypatch.setattr(os, "replace", real_replace)
    result = pump_lead_recover.recover_overdue_pump_leads(path=str(path), hydrate=False)
    assert result["ok"] is True
    assert calls == [1]
    assert json.loads(path.read_text())["resolved"][0]["learning"]["state"] == "applied"


def test_pump_pending_learning_recovers_after_commit_crash(tmp_path, monkeypatch):
    path = _pump_ledger(tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(pump_calibration, "maybe_adapt_after_resolve", lambda **_kw: calls.append(1))
    real_write = predictions_store._write_predictions_unlocked

    def crash_after_commit(data, **kwargs):
        real_write(data, **kwargs)
        if any(row.get("learning", {}).get("state") == "pending" for row in data["resolved"]):
            raise SystemExit("crash after ledger commit")

    monkeypatch.setattr(predictions_store, "_write_predictions_unlocked", crash_after_commit)
    with pytest.raises(SystemExit):
        pump_lead_recover.recover_overdue_pump_leads(path=str(path), hydrate=False)
    assert calls == []
    monkeypatch.setattr(predictions_store, "_write_predictions_unlocked", real_write)
    pump_lead_recover.recover_overdue_pump_leads(path=str(path), hydrate=False)
    assert calls == [1]
    row = json.loads(path.read_text())["resolved"][0]
    assert row["learning"]["state"] == "applied"


def test_pump_crash_during_calibration_is_not_repeated(tmp_path, monkeypatch):
    path = _pump_ledger(tmp_path, monkeypatch)
    calls = []

    def crash(**_kw):
        calls.append(1)
        raise SystemExit("crash during calibration")

    monkeypatch.setattr(pump_calibration, "maybe_adapt_after_resolve", crash)
    with pytest.raises(SystemExit):
        pump_lead_recover.recover_overdue_pump_leads(path=str(path), hydrate=False)
    monkeypatch.setattr(pump_calibration, "maybe_adapt_after_resolve", lambda **_kw: calls.append(1))
    result = pump_lead_recover.recover_overdue_pump_leads(path=str(path), hydrate=False)
    assert calls == [1]
    row = json.loads(path.read_text())["resolved"][0]
    assert row["learning"]["state"] == "indeterminate"
    assert result["learning_indeterminate"] == 1
    later = pump_lead_recover.recover_overdue_pump_leads(path=str(path), hydrate=False)
    assert later["ok"] is False
    assert later["learning_indeterminate"] == 1


def test_concurrent_pump_reconcile_does_not_steal_live_claim(tmp_path, monkeypatch):
    path = _pump_ledger(tmp_path, monkeypatch)
    entered = threading.Event()
    release = threading.Event()
    calls = []
    errors = []

    def calibrate(**_kw):
        calls.append(1)
        entered.set()
        assert release.wait(5)

    def recover():
        try:
            pump_lead_recover.recover_overdue_pump_leads(path=str(path), hydrate=False)
        except BaseException as exc:
            errors.append(exc)

    monkeypatch.setattr(pump_calibration, "maybe_adapt_after_resolve", calibrate)
    first = threading.Thread(target=recover)
    second = threading.Thread(target=recover)
    first.start()
    assert entered.wait(5)
    second.start()
    second.join(2)
    second_finished = not second.is_alive()
    release.set()
    first.join(5)
    second.join(5)
    assert second_finished
    assert not errors
    assert calls == [1]


def test_stale_learning_owner_cannot_finish_replacement_claim(tmp_path):
    path = tmp_path / "predictions.json"
    path.write_text(json.dumps({
        "predictions": [],
        "resolved": [{
            "id": "pump-1",
            "learning": {
                "key": "learning-key", "kind": "pump", "state": "claimed",
                "owner": {"boot_id": "new-boot", "cycle_run_id": "new-cycle"},
                "done": [], "warnings": [],
            },
        }],
        "stats": {},
    }))

    result = learning_effects._change_learning(
        str(path), "learning-key",
        lambda item: item.get("state") == "claimed" and item.get("owner") == {
            "boot_id": "old-boot", "cycle_run_id": "old-cycle",
        },
        lambda item: item.update(state="applied"),
    )
    assert result.outcome is predictions_store.PersistOutcome.REFUSED
    assert json.loads(path.read_text())["resolved"][0]["learning"]["state"] == "claimed"


def test_worker_replaced_while_effect_runs_cannot_mark_new_owner_applied(tmp_path, monkeypatch):
    path = _pump_ledger(tmp_path, monkeypatch)
    original_change = learning_effects._change_learning
    calls = 0

    def replace_owner_before_finish(ledger_path, key, expected, change):
        nonlocal calls
        calls += 1
        if calls == 2:
            def replace(data, _raw):
                data["resolved"][0]["learning"]["owner"] = {
                    "boot_id": "replacement-boot", "cycle_run_id": "replacement-cycle",
                }
                return data, [key], []
            predictions_store.mutate_predictions(
                replace, path=ledger_path, caller="test-replace-owner", trigger="race",
            )
        return original_change(ledger_path, key, expected, change)

    monkeypatch.setattr(learning_effects, "_change_learning", replace_owner_before_finish)
    result = pump_lead_recover.recover_overdue_pump_leads(path=str(path), hydrate=False)
    row = json.loads(path.read_text())["resolved"][0]
    assert row["learning"]["state"] == "claimed"
    assert row["learning"]["owner"]["boot_id"] == "replacement-boot"
    assert result["learning_failed"] == 1
