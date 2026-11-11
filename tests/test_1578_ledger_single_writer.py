import json
from contextlib import contextmanager

from internal.council import replay
from internal.learning import expert_backfill, expired_recovery, predictions_store


def _write_ledger(path, *, pending=None, resolved=None):
    path.write_text(
        json.dumps({"predictions": pending or [], "resolved": resolved or [], "stats": {}})
    )


def _append_concurrent(path):
    assert predictions_store.append_prediction(
        {
            "id": "concurrent",
            "netuid": 999,
            "horizon_type": "hour",
            "status": "pending",
        },
        path=str(path),
    )


def _assert_concurrent_survives(path):
    data = json.loads(path.read_text())
    assert any(row.get("id") == "concurrent" for row in data["predictions"])


def test_backfill_preserves_concurrent_append(tmp_path, monkeypatch):
    path = tmp_path / "predictions.json"
    _write_ledger(path, pending=[{"id": "existing", "netuid": 1, "status": "pending"}])
    monkeypatch.setattr(predictions_store, "PREDICTIONS_PATH", str(path))
    appended = False

    def attribution(_row):
        nonlocal appended
        if not appended:
            appended = True
            _append_concurrent(path)
        return "dark_horse", "test"

    monkeypatch.setattr(expert_backfill, "resolve_expert_attribution", attribution)
    expert_backfill.backfill_expert_attribution(dry_run=False)
    _assert_concurrent_survives(path)


def test_replay_preserves_concurrent_append(tmp_path, monkeypatch):
    path = tmp_path / "predictions.json"
    _write_ledger(
        path,
        pending=[{"id": "existing", "netuid": 1, "status": "pending", "created_at": "2026-01-01T00:00:00Z"}],
    )
    appended = False

    def resolve(row):
        nonlocal appended
        if not appended:
            appended = True
            _append_concurrent(path)
        return row

    monkeypatch.setattr(replay, "resolve_prediction_at_horizon", resolve)
    monkeypatch.setattr(replay, "rebuild_judge_portfolios_from_stream", lambda *_a, **_kw: {})
    replay.replay_predictions(predictions_path=str(path), portfolios_path=str(tmp_path / "portfolios.json"))
    _assert_concurrent_survives(path)


def test_expired_recovery_preserves_concurrent_append(tmp_path, monkeypatch):
    from internal.council import price_reference, resolver
    from internal.council import capture

    path = tmp_path / "predictions.json"
    _write_ledger(
        path,
        resolved=[{
            "id": "expired", "netuid": 1, "outcome": "expired",
            "resolve_at": "2026-01-01T00:00:00Z", "reference_price": 1,
            "prediction": {"direction": "up"},
        }],
    )
    monkeypatch.setattr(predictions_store, "PREDICTIONS_PATH", str(path))

    def price(_netuid, _resolve_at):
        _append_concurrent(path)
        return "ok", 1.1, {}

    monkeypatch.setattr(price_reference, "price_at_resolve_at", price)
    monkeypatch.setattr(capture, "stamp_capture_fields", lambda *_a, **_kw: {})
    monkeypatch.setattr(resolver, "_stamp_and_nudge_expert", lambda *_a, **_kw: (None, None))
    monkeypatch.setattr(resolver, "_ensure_subnet_snapshot", lambda *_a, **_kw: None)
    monkeypatch.setattr(resolver, "_skip_council_learning", lambda *_a, **_kw: True)
    monkeypatch.setattr(resolver, "atomic_finalize_resolution", lambda *_a, **_kw: None)
    monkeypatch.setattr(
        "internal.learning.pump_calibration.maybe_adapt_after_resolve",
        lambda *_a, **_kw: None,
    )
    expired_recovery.recover_expired_predictions()
    _assert_concurrent_survives(path)


def test_pump_recovery_preserves_concurrent_append(tmp_path, monkeypatch):
    from internal.council import price_reference
    from internal.learning import pump_lead_recover

    path = tmp_path / "predictions.json"
    _write_ledger(
        path,
        pending=[{
            "id": "pump", "netuid": 1, "status": "pending",
            "resolve_at": "2026-01-01T00:00:00Z", "horizon_type": "hour",
        }],
    )
    monkeypatch.setattr(pump_lead_recover, "is_pump_desk_claim", lambda row: row.get("id") == "pump")
    monkeypatch.setattr(price_reference, "_load_cache", lambda *_a, **_kw: {})
    monkeypatch.setattr(pump_lead_recover, "update_pump_horizon_outcomes", lambda *_a, **_kw: 0)
    monkeypatch.setattr(
        "internal.learning.pump_calibration.maybe_adapt_after_resolve",
        lambda *_a, **_kw: None,
    )

    def grade(row, **_kwargs):
        _append_concurrent(path)
        return {**row, "status": "resolved", "correct": True}

    monkeypatch.setattr(pump_lead_recover, "grade_pump_lead_at_resolve_candle", grade)
    pump_lead_recover.recover_overdue_pump_leads(path=str(path), hydrate=False)
    _assert_concurrent_survives(path)


def test_resolver_expiry_preserves_concurrent_append(tmp_path, monkeypatch):
    from internal.council import resolver

    path = tmp_path / "predictions.json"
    _write_ledger(
        path,
        pending=[{"id": "old", "netuid": 1, "status": "pending", "horizon_type": "hour"}],
    )
    monkeypatch.setattr(resolver, "PREDICTIONS_PATH", str(path))
    old_expire = resolver._expire_prediction

    def expire(row, now):
        _append_concurrent(path)
        return old_expire(row, now)

    monkeypatch.setattr(resolver, "_expire_prediction", expire)
    resolver.expire_stale_predictions()
    _assert_concurrent_survives(path)


def test_backfill_does_not_overwrite_competing_resolution(tmp_path, monkeypatch):
    path = tmp_path / "predictions.json"
    _write_ledger(path, pending=[{"id": "existing", "netuid": 1, "status": "pending"}])
    monkeypatch.setattr(predictions_store, "PREDICTIONS_PATH", str(path))

    def attribution(_row):
        current = predictions_store.load_predictions(path=str(path), fail_closed=True)
        row = current["predictions"].pop()
        current["resolved"].append({**row, "status": "resolved", "outcome": "hit"})
        predictions_store.save_predictions(current, path=str(path))
        return "dark_horse", "test"

    monkeypatch.setattr(expert_backfill, "resolve_expert_attribution", attribution)
    expert_backfill.backfill_expert_attribution(dry_run=False)
    data = json.loads(path.read_text())
    assert not any(row.get("id") == "existing" for row in data["predictions"])
    assert any(row.get("id") == "existing" and row.get("outcome") == "hit" for row in data["resolved"])


def test_backfill_on_unmigrated_legacy_row_applies(tmp_path, monkeypatch):
    path = tmp_path / "predictions.json"
    _write_ledger(path, pending=[{"id": "legacy", "netuid": 1, "phase_at_prediction": "ACCUMULATION"}])
    monkeypatch.setattr(predictions_store, "PREDICTIONS_PATH", str(path))
    monkeypatch.setattr(
        expert_backfill, "resolve_expert_attribution", lambda _row: ("dark_horse", "test")
    )
    expert_backfill.backfill_expert_attribution(dry_run=False)
    data = json.loads(path.read_text())
    assert data["predictions"][0]["expert"] == "dark_horse"


def test_backfill_refuses_unidentifiable_legacy_row(tmp_path, monkeypatch):
    path = tmp_path / "predictions.json"
    _write_ledger(path, pending=[{"netuid": 1, "created_at": "2026-01-01T00:00:00Z"}])
    monkeypatch.setattr(predictions_store, "PREDICTIONS_PATH", str(path))
    monkeypatch.setattr(
        expert_backfill, "resolve_expert_attribution", lambda _row: ("dark_horse", "test")
    )
    result = expert_backfill.backfill_expert_attribution(dry_run=False)
    assert result["updated"] == 0
    assert "expert" not in json.loads(path.read_text())["predictions"][0]


def test_mutator_refuses_invalid_ledger_without_writing(tmp_path):
    path = tmp_path / "predictions.json"
    path.write_text('{"predictions": null, "resolved": [], "stats": {}}')
    before = path.read_bytes()
    result = predictions_store.mutate_predictions(
        lambda data, raw: (data, [], []),
        path=str(path),
        caller="test",
        trigger="invalid",
    )
    assert result.outcome in (
        predictions_store.PersistOutcome.REFUSED,
        predictions_store.PersistOutcome.FAILED,
    )
    assert path.read_bytes() == before


def test_mutator_reports_conflict_without_writing(tmp_path):
    path = tmp_path / "predictions.json"
    _write_ledger(path)
    before = path.read_bytes()
    result = predictions_store.mutate_predictions(
        lambda data, raw: (data, [], ["existing"]),
        path=str(path),
        caller="test",
        trigger="conflict",
    )
    assert result.outcome == predictions_store.PersistOutcome.REFUSED
    assert result.reason == predictions_store.PersistReason.CONFLICT_ONLY
    assert path.read_bytes() == before


def test_mutator_reports_lock_timeout(tmp_path, monkeypatch):
    @contextmanager
    def timeout(*_args, **_kwargs):
        raise predictions_store.FileLockTimeout("busy")
        yield

    monkeypatch.setattr(predictions_store, "locked_predictions_file", timeout)
    result = predictions_store.mutate_predictions(
        lambda data, raw: (data, ["changed"], []),
        path=str(tmp_path / "predictions.json"),
        caller="test",
        trigger="timeout",
    )
    assert result.outcome == predictions_store.PersistOutcome.FAILED
    assert result.reason == predictions_store.PersistReason.LOCK_TIMEOUT


def test_append_duplicate_is_not_written_twice(tmp_path):
    path = tmp_path / "predictions.json"
    _write_ledger(path)
    prediction = {"id": "a", "netuid": 17, "status": "pending", "horizon_type": "hour"}
    assert predictions_store.append_prediction(dict(prediction), path=str(path)) is True
    assert predictions_store.append_prediction(dict(prediction), path=str(path)) is False
    assert len(json.loads(path.read_text())["predictions"]) == 1


def test_append_does_not_migrate_unidentifiable_legacy_row(tmp_path):
    path = tmp_path / "predictions.json"
    legacy = {"netuid": 1, "expert": "contrarian", "status": "pending"}
    _write_ledger(path, pending=[legacy])
    assert predictions_store.append_prediction(
        {"id": "new", "netuid": 17, "status": "pending", "horizon_type": "hour"},
        path=str(path),
    )
    assert json.loads(path.read_text())["predictions"][0] == legacy


def test_mutator_reports_failure_before_replace(tmp_path, monkeypatch):
    path = tmp_path / "predictions.json"
    _write_ledger(path)
    before = path.read_bytes()
    monkeypatch.setattr(
        predictions_store, "_write_predictions_unlocked",
        lambda *_a, **_kw: (_ for _ in ()).throw(OSError("before replace")),
    )
    result = predictions_store.mutate_predictions(
        lambda data, raw: (data, ["changed"], []),
        path=str(path), caller="test", trigger="before_replace",
    )
    assert result.outcome == predictions_store.PersistOutcome.FAILED
    assert result.reason == predictions_store.PersistReason.IO_ERROR
    assert path.read_bytes() == before


def test_mutator_recognizes_commit_after_replace_error(tmp_path, monkeypatch):
    from internal.ops import mutation_log

    path = tmp_path / "predictions.json"
    _write_ledger(path)
    real_log = mutation_log.log_mutation

    def log_mutation(*_args, **kwargs):
        if kwargs.get("operation") == "completed":
            raise OSError("after replace")
        return real_log(*_args, **kwargs)

    monkeypatch.setattr(mutation_log, "log_mutation", log_mutation)

    def add(data, _raw):
        data["predictions"].append({"id": "new", "netuid": 23})
        return data, ["new"], []

    result = predictions_store.mutate_predictions(
        add, path=str(path), caller="test", trigger="after_replace",
    )
    assert result.outcome == predictions_store.PersistOutcome.APPLIED
    assert json.loads(path.read_text())["predictions"][0]["id"] == "new"


def test_mutator_reports_indeterminate_if_post_replace_read_fails(tmp_path, monkeypatch):
    from internal.ops import mutation_log

    path = tmp_path / "predictions.json"
    _write_ledger(path)
    real_load = predictions_store.load_predictions
    real_log = mutation_log.log_mutation
    reads = 0

    def load(**kwargs):
        nonlocal reads
        reads += 1
        if reads > 1:
            raise predictions_store.PredictionsLedgerUnreadable("unreadable")
        return real_load(**kwargs)

    def log_mutation(*_args, **kwargs):
        if kwargs.get("operation") == "completed":
            raise OSError("after replace")
        return real_log(*_args, **kwargs)

    monkeypatch.setattr(predictions_store, "load_predictions", load)
    monkeypatch.setattr(mutation_log, "log_mutation", log_mutation)
    result = predictions_store.mutate_predictions(
        lambda data, raw: (data, ["changed"], []),
        path=str(path), caller="test", trigger="indeterminate",
    )
    assert result.outcome == predictions_store.PersistOutcome.INDETERMINATE


def test_mutator_reports_failed_if_replaced_state_is_absent(tmp_path, monkeypatch):
    path = tmp_path / "predictions.json"
    _write_ledger(path)

    def missing_write(*_args, **kwargs):
        kwargs["on_replaced"]()
        raise OSError("after replace")

    monkeypatch.setattr(predictions_store, "_write_predictions_unlocked", missing_write)

    def add(data, _raw):
        data["predictions"].append({"id": "new", "netuid": 23})
        return data, ["new"], []

    result = predictions_store.mutate_predictions(
        add, path=str(path), caller="test", trigger="missing_after_replace",
    )
    assert result.outcome == predictions_store.PersistOutcome.FAILED


def test_revoked_cycle_skips_ledger_write(tmp_path, monkeypatch):
    from internal.council import resolver

    path = tmp_path / "predictions.json"
    _write_ledger(path)
    before = path.read_bytes()
    monkeypatch.setattr(resolver, "_cycle_writes_revoked_safe", lambda: True)
    result = resolver._commit_predictions_mutation(
        lambda data, raw: (data, ["changed"], []),
        path=str(path), caller="test", trigger="revoked",
    )
    assert result.outcome == predictions_store.PersistOutcome.SKIPPED_ABANDONED
    assert path.read_bytes() == before
