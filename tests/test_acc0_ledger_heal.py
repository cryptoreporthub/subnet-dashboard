"""Acc-0 — daily pick ledger heal + epoch reset footgun."""

from __future__ import annotations

import json
import inspect
import os
import threading
from datetime import datetime, timezone
from pathlib import Path

from internal.learning.ledger_heal import (
    archive_predictions_epoch,
    heal_daily_pick_ledger,
)
from internal.learning.loop_health import build_learning_loop_health


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _sample_pick(netuid: int = 15, price: float = 1.23) -> dict:
    return {
        "action": "long",
        "final_confidence": 0.485,
        "subnet": {"netuid": netuid, "name": f"SN{netuid}", "price": price},
        "prediction": {
            "predicted_pct": 2.5,
            "horizon_hours": 4,
            "reference_price": price,
        },
    }


def _reset_with_id(preds, archive, request_id):
    kwargs = {
        "predictions_path": str(preds), "archive_dir": str(archive),
        "re_heal_daily": False,
    }
    if "reset_request_id" in inspect.signature(archive_predictions_epoch).parameters:
        kwargs["reset_request_id"] = request_id
    return archive_predictions_epoch(**kwargs)


def test_epoch_same_second_does_not_overwrite_prior_archive(tmp_path, monkeypatch):
    from internal.learning import ledger_heal

    preds, archive = tmp_path / "predictions.json", tmp_path / "archive"
    fixed = datetime(2026, 8, 18, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(ledger_heal, "_utcnow", lambda: fixed)
    first = {"predictions": [], "resolved": [{"id": "first"}], "stats": {}}
    _write_json(preds, first)
    first_bytes = preds.read_bytes()
    one = _reset_with_id(preds, archive, "11111111-1111-4111-8111-111111111111")
    doc = json.loads(preds.read_text())
    doc["resolved"].append({"id": "second"})
    _write_json(preds, doc)
    second_bytes = preds.read_bytes()
    two = _reset_with_id(preds, archive, "22222222-2222-4222-8222-222222222222")
    assert one["ok"] and two["ok"]
    assert one["archive_path"] != two["archive_path"]
    assert Path(one["archive_path"]).read_bytes() == first_bytes
    assert Path(two["archive_path"]).read_bytes() == second_bytes


def test_epoch_old_retry_after_later_reset_does_not_clear_new_rows(tmp_path):
    preds, archive = tmp_path / "predictions.json", tmp_path / "archive"
    _write_json(preds, {"predictions": [], "resolved": [{"id": "first"}], "stats": {}})
    first = "11111111-1111-4111-8111-111111111111"
    second = "22222222-2222-4222-8222-222222222222"
    assert _reset_with_id(preds, archive, first)["ok"]
    doc = json.loads(preds.read_text())
    doc["resolved"].append({"id": "second"})
    _write_json(preds, doc)
    assert _reset_with_id(preds, archive, second)["ok"]
    doc = json.loads(preds.read_text())
    doc["resolved"].append({"id": "after-both"})
    _write_json(preds, doc)
    before = preds.read_bytes()
    result = _reset_with_id(preds, archive, first)
    assert result["ok"] is True
    assert preds.read_bytes() == before


def test_epoch_interrupted_publication_recovers_without_second_clear(tmp_path, monkeypatch):
    preds, archive = tmp_path / "predictions.json", tmp_path / "archive"
    _write_json(preds, {"predictions": [], "resolved": [{"id": "first"}], "stats": {}})
    request_id = "11111111-1111-4111-8111-111111111111"
    real_replace = os.replace

    def interrupted(src, dst):
        if Path(dst).parent == archive and Path(dst).name.startswith("pre-epoch-"):
            raise OSError("crash before publication")
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", interrupted)
    result = _reset_with_id(preds, archive, request_id)
    assert result["ok"] is False
    doc = json.loads(preds.read_text())
    assert doc["resolved"] == []
    doc["resolved"].append({"id": "after-commit"})
    _write_json(preds, doc)
    before = preds.read_bytes()
    monkeypatch.setattr(os, "replace", real_replace)
    retry = _reset_with_id(preds, archive, request_id)
    assert retry["ok"] is True
    assert preds.read_bytes() == before
    assert Path(retry["archive_path"]).is_file()


def test_epoch_missing_published_archive_cannot_report_retry_success(tmp_path):
    preds, archive = tmp_path / "predictions.json", tmp_path / "archive"
    _write_json(preds, {"predictions": [], "resolved": [{"id": "first"}], "stats": {}})
    request_id = "11111111-1111-4111-8111-111111111111"
    result = _reset_with_id(preds, archive, request_id)
    Path(result["archive_path"]).unlink()
    retry = _reset_with_id(preds, archive, request_id)
    assert retry["ok"] is False
    assert retry["reason"] == "archive_missing"


def test_epoch_retry_identity_survives_more_than_fifty_later_resets(tmp_path):
    preds, archive = tmp_path / "predictions.json", tmp_path / "archive"
    _write_json(preds, {"predictions": [], "resolved": [{"id": "first"}], "stats": {}})
    request_id = "11111111-1111-4111-8111-111111111111"
    assert _reset_with_id(preds, archive, request_id)["ok"]
    doc = json.loads(preds.read_text())
    history = doc.get("epoch_history", [])
    for n in range(51):
        history.append({**(history[0] if history else {}), "reset_request_id": f"later-{n}"})
    doc["epoch_history"] = history
    doc["resolved"].append({"id": "new"})
    _write_json(preds, doc)
    before = preds.read_bytes()
    assert _reset_with_id(preds, archive, request_id)["ok"]
    assert preds.read_bytes() == before


def test_epoch_concurrent_append_survives_snapshot_and_clear(tmp_path, monkeypatch):
    from internal.learning import predictions_store
    from internal.store import soul_map_io

    preds, archive = tmp_path / "predictions.json", tmp_path / "archive"
    _write_json(preds, {"predictions": [], "resolved": [{"id": "first"}], "stats": {}})
    entered, release = threading.Event(), threading.Event()
    original_read = soul_map_io.read_blob_checked
    errors = []

    def checked(*args, **kwargs):
        result = original_read(*args, **kwargs)
        if threading.current_thread().name == "reset-test" and not entered.is_set():
            entered.set()
            assert release.wait(5)
        return result

    def reset():
        try:
            _reset_with_id(preds, archive, "11111111-1111-4111-8111-111111111111")
        except BaseException as exc:
            errors.append(exc)

    def append():
        try:
            predictions_store.append_prediction(
                {"id": "new", "netuid": 99, "horizon_type": "hour", "status": "pending"},
                path=str(preds),
            )
        except BaseException as exc:
            errors.append(exc)

    monkeypatch.setattr(soul_map_io, "read_blob_checked", checked)
    reset_thread = threading.Thread(target=reset, name="reset-test")
    append_thread = threading.Thread(target=append)
    reset_thread.start()
    assert entered.wait(5)
    append_thread.start()
    append_thread.join(0.5)
    release.set()
    reset_thread.join(5)
    append_thread.join(5)
    assert not errors
    assert any(row.get("id") == "new" for row in json.loads(preds.read_text())["predictions"])


def test_reset_script_reuses_pending_request_after_failure(tmp_path, monkeypatch):
    import sys
    from scripts import reset_accuracy_epoch

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["reset_accuracy_epoch.py", "--no-heal"])
    seen = []

    def reset(**kwargs):
        seen.append(kwargs.get("reset_request_id"))
        return {"ok": len(seen) > 1}

    monkeypatch.setattr(reset_accuracy_epoch, "archive_predictions_epoch", reset)
    assert reset_accuracy_epoch.main() == 1
    assert reset_accuracy_epoch.main() == 0
    assert seen[0] and seen[0] == seen[1]


def test_epoch_does_not_delete_recent_uncommitted_stage(tmp_path):
    preds, archive = tmp_path / "predictions.json", tmp_path / "archive"
    archive.mkdir()
    stage = archive / ".staging-22222222-2222-4222-8222-222222222222.json"
    stage.write_text("in-flight")
    _write_json(preds, {"predictions": [], "resolved": [{"id": "first"}], "stats": {}})
    assert _reset_with_id(preds, archive, "11111111-1111-4111-8111-111111111111")["ok"]
    assert stage.read_text() == "in-flight"


def test_epoch_reconcile_publishes_staged_archive_after_commit(tmp_path, monkeypatch):
    from internal.learning import ledger_heal

    preds, archive = tmp_path / "predictions.json", tmp_path / "archive"
    _write_json(preds, {"predictions": [], "resolved": [{"id": "first"}], "stats": {}})
    real_replace = os.replace

    def interrupted(src, dst):
        if Path(dst).parent == archive and Path(dst).name.startswith("pre-epoch-"):
            raise OSError("interrupted publication")
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", interrupted)
    result = _reset_with_id(preds, archive, "11111111-1111-4111-8111-111111111111")
    assert result["ok"] is False
    before = preds.read_bytes()
    monkeypatch.setattr(os, "replace", real_replace)
    assert ledger_heal.reconcile_epoch_archives(
        predictions_path=str(preds), archive_dir=str(archive)
    )["ok"] is True
    assert preds.read_bytes() == before
    assert len(list(archive.glob("pre-epoch-*.json"))) == 1


def test_epoch_archive_refuses_unreadable_ledger_without_write(tmp_path):
    preds = tmp_path / "predictions.json"
    preds.write_text("not-json{{{", encoding="utf-8")
    before = preds.read_bytes()

    summary = archive_predictions_epoch(
        reset_request_id="11111111-1111-4111-8111-111111111111",
        predictions_path=str(preds),
        archive_dir=str(tmp_path / "arc"),
        re_heal_daily=False,
    )
    assert summary["ok"] is False
    assert summary["reason"] == "ledger_unreadable"
    assert preds.read_bytes() == before


def test_heal_refuses_unreadable_ledger_without_write(tmp_path, monkeypatch):
    preds = tmp_path / "predictions.json"
    daily = tmp_path / "daily_picks.json"
    preds.write_text("corrupt", encoding="utf-8")
    daily.write_text(
        json.dumps(
            [
                {
                    "date": _today(),
                    "action": "long",
                    "has_pick": True,
                    "pick_netuid": 15,
                    "pick": _sample_pick(),
                    "market_context": {},
                }
            ]
        ),
        encoding="utf-8",
    )
    before = preds.read_bytes()
    monkeypatch.setattr("internal.learning.predictions_store.PREDICTIONS_PATH", str(preds))

    summary = heal_daily_pick_ledger(
        dry_run=False, daily_picks_path=str(daily), predictions_path=str(preds)
    )
    assert summary["ok"] is False
    assert summary["reason"] == "ledger_unreadable"
    assert preds.read_bytes() == before


def test_heal_backfills_gap(tmp_path, monkeypatch):
    daily = tmp_path / "daily_picks.json"
    preds = tmp_path / "predictions.json"
    _write_json(
        daily,
        [
            {
                "date": _today(),
                "action": "long",
                "pick": _sample_pick(),
                "market_context": {},
            }
        ],
    )
    _write_json(preds, {"predictions": [], "resolved": [], "stats": {"pending": 0}})

    monkeypatch.setattr("internal.learning.predictions_store.PREDICTIONS_PATH", str(preds))
    monkeypatch.setattr("internal.learning.ledger_heal.DAILY_PICKS_PATH", str(daily))
    monkeypatch.setattr(
        "internal.council.resolver_scheduler.get_prediction_resolver_scheduler_state",
        lambda: {"running": True, "last_run_at": datetime.now(timezone.utc).isoformat()},
    )

    summary = heal_daily_pick_ledger(dry_run=False, daily_picks_path=str(daily))
    assert summary["ok"] is True
    assert summary["healed"] is True

    report = build_learning_loop_health(
        daily_picks_path=str(daily),
        predictions_path=str(preds),
        soul_path=str(tmp_path / "missing_soul.json"),
    )
    assert report["ledger"]["gap"] is False


def test_heal_uses_prediction_reference_price(tmp_path, monkeypatch):
    daily = tmp_path / "daily_picks.json"
    preds = tmp_path / "predictions.json"
    pick = {
        "action": "long",
        "subnet": {"netuid": 15, "name": "SN15"},
        "prediction": {"reference_price": 0.0198846, "predicted_pct": 2.5, "horizon_hours": 4},
    }
    _write_json(
        daily,
        [{"date": _today(), "action": "long", "pick": pick, "market_context": {}}],
    )
    _write_json(preds, {"predictions": [], "resolved": [], "stats": {"pending": 0}})

    monkeypatch.setattr("internal.learning.predictions_store.PREDICTIONS_PATH", str(preds))
    monkeypatch.setattr("internal.learning.ledger_heal.DAILY_PICKS_PATH", str(daily))

    summary = heal_daily_pick_ledger(dry_run=False, daily_picks_path=str(daily))
    assert summary["healed"] is True
    assert summary["netuid"] == 15


def test_heal_no_duplicate_after_corrupt_then_restore(tmp_path, monkeypatch):
    """Operator repairs ledger mid-cycle; second heal must not add a duplicate day row."""
    daily = tmp_path / "daily_picks.json"
    preds = tmp_path / "predictions.json"
    _write_json(
        daily,
        [{"date": _today(), "action": "long", "pick": _sample_pick(), "market_context": {}}],
    )
    _write_json(preds, {"predictions": [], "resolved": [], "stats": {"pending": 0}})

    monkeypatch.setattr("internal.learning.predictions_store.PREDICTIONS_PATH", str(preds))
    monkeypatch.setattr("internal.learning.ledger_heal.DAILY_PICKS_PATH", str(daily))

    first = heal_daily_pick_ledger(dry_run=False, daily_picks_path=str(daily))
    assert first["healed"] is True
    good_bytes = preds.read_bytes()

    preds.write_text("corrupt", encoding="utf-8")
    blocked = heal_daily_pick_ledger(dry_run=False, daily_picks_path=str(daily))
    assert blocked["reason"] == "ledger_unreadable"

    preds.write_bytes(good_bytes)
    again = heal_daily_pick_ledger(dry_run=False, daily_picks_path=str(daily))
    assert again["healed"] is False
    assert again["reason"] in ("ledger_present", "duplicate_skipped")

    data = json.loads(preds.read_text(encoding="utf-8"))
    day_rows = [
        r
        for r in data.get("predictions", [])
        if r.get("horizon_type") == "day" and not r.get("shadow")
    ]
    assert len(day_rows) == 1


def test_heal_idempotent(tmp_path, monkeypatch):
    daily = tmp_path / "daily_picks.json"
    preds = tmp_path / "predictions.json"
    _write_json(
        daily,
        [{"date": _today(), "action": "long", "pick": _sample_pick(), "market_context": {}}],
    )
    _write_json(preds, {"predictions": [], "resolved": [], "stats": {"pending": 0}})

    monkeypatch.setattr("internal.learning.predictions_store.PREDICTIONS_PATH", str(preds))
    monkeypatch.setattr("internal.learning.ledger_heal.DAILY_PICKS_PATH", str(daily))

    first = heal_daily_pick_ledger(dry_run=False, daily_picks_path=str(daily))
    second = heal_daily_pick_ledger(dry_run=False, daily_picks_path=str(daily))
    assert first["healed"] is True
    assert second["healed"] is False
    assert second["reason"] == "ledger_present"

    data = json.loads(preds.read_text(encoding="utf-8"))
    day_rows = [
        r
        for r in data.get("predictions", [])
        if r.get("horizon_type") == "day" and not r.get("shadow")
    ]
    assert len(day_rows) == 1


def test_heal_dry_run_no_write(tmp_path, monkeypatch):
    daily = tmp_path / "daily_picks.json"
    preds = tmp_path / "predictions.json"
    _write_json(
        daily,
        [{"date": _today(), "action": "long", "pick": _sample_pick(), "market_context": {}}],
    )
    _write_json(preds, {"predictions": [], "resolved": [], "stats": {"pending": 0}})

    monkeypatch.setattr("internal.learning.predictions_store.PREDICTIONS_PATH", str(preds))
    monkeypatch.setattr("internal.learning.ledger_heal.DAILY_PICKS_PATH", str(daily))

    summary = heal_daily_pick_ledger(dry_run=True, daily_picks_path=str(daily))
    assert summary["dry_run"] is True
    assert summary["would_record"] == 15
    data = json.loads(preds.read_text(encoding="utf-8"))
    assert data.get("predictions") == []


def test_epoch_reset_reheals_or_downgrades(tmp_path, monkeypatch):
    daily = tmp_path / "daily_picks.json"
    preds = tmp_path / "predictions.json"
    archive = tmp_path / "archive"
    _write_json(
        daily,
        [{"date": _today(), "action": "long", "pick": _sample_pick(), "market_context": {}}],
    )
    _write_json(
        preds,
        {
            "predictions": [{"netuid": 99, "horizon_type": "day", "status": "pending"}],
            "resolved": [],
            "stats": {"pending": 1},
        },
    )

    monkeypatch.setattr("internal.learning.predictions_store.PREDICTIONS_PATH", str(preds))
    monkeypatch.setattr("internal.learning.ledger_heal.DAILY_PICKS_PATH", str(daily))
    monkeypatch.setattr("internal.learning.ledger_heal.ARCHIVE_DIR", str(archive))
    monkeypatch.setattr(
        "internal.council.resolver_scheduler.get_prediction_resolver_scheduler_state",
        lambda: {"running": True, "last_run_at": datetime.now(timezone.utc).isoformat()},
    )

    summary = archive_predictions_epoch(reset_request_id="11111111-1111-4111-8111-111111111111")
    assert summary["ok"] is True
    assert summary["archive_path"] is not None

    data = json.loads(preds.read_text(encoding="utf-8"))
    assert data.get("predictions")  # reheal should add today's row
    day_rows = [r for r in data["predictions"] if r.get("horizon_type") == "day"]
    assert any(int(r.get("netuid", 0)) == 15 for r in day_rows)

    report = build_learning_loop_health(
        daily_picks_path=str(daily),
        predictions_path=str(preds),
        soul_path=str(tmp_path / "missing_soul.json"),
    )
    assert report["ledger"]["gap"] is False


def test_epoch_archive_uses_alternate_predictions_path(tmp_path, monkeypatch):
    daily = tmp_path / "daily_picks.json"
    preds = tmp_path / "alt_predictions.json"
    archive = tmp_path / "archive"
    _write_json(
        daily,
        [{"date": _today(), "action": "long", "pick": _sample_pick(), "market_context": {}}],
    )
    _write_json(
        preds,
        {
            "predictions": [],
            "resolved": [{"id": "old", "correct": True}],
            "stats": {"correct": 1, "wrong": 0, "pending": 0, "total": 1, "accuracy": 1.0},
        },
    )
    monkeypatch.setattr("internal.learning.ledger_heal.DAILY_PICKS_PATH", str(daily))
    monkeypatch.setattr(
        "internal.council.resolver_scheduler.get_prediction_resolver_scheduler_state",
        lambda: {"running": True, "last_run_at": datetime.now(timezone.utc).isoformat()},
    )

    summary = archive_predictions_epoch(
        reset_request_id="11111111-1111-4111-8111-111111111111",
        predictions_path=str(preds),
        archive_dir=str(archive),
        re_heal_daily=False,
    )
    assert summary["ok"] is True
    data = json.loads(preds.read_text(encoding="utf-8"))
    assert data.get("resolved") == []
    assert data["epoch_history"][0]["reset_request_id"] == "11111111-1111-4111-8111-111111111111"


def test_heal_append_unreadable(tmp_path, monkeypatch):
    preds = tmp_path / "predictions.json"
    daily = tmp_path / "daily_picks.json"
    _write_json(
        preds,
        {"predictions": [], "resolved": [], "stats": {"pending": 0, "total": 0}},
    )
    daily.write_text(
        json.dumps(
            [{"date": _today(), "action": "long", "pick": _sample_pick(), "market_context": {}}]
        ),
        encoding="utf-8",
    )
    before = preds.read_bytes()
    monkeypatch.setattr("internal.learning.ledger_heal.DAILY_PICKS_PATH", str(daily))

    from internal.learning.predictions_store import PredictionsLedgerUnreadable

    def _append_raises_unreadable(*_a, **_k):
        raise PredictionsLedgerUnreadable("unreadable", error="simulated after initial read")

    monkeypatch.setattr(
        "internal.learning.prediction_loop.append_prediction",
        _append_raises_unreadable,
    )

    summary = heal_daily_pick_ledger(
        dry_run=False,
        daily_picks_path=str(daily),
        predictions_path=str(preds),
    )
    assert summary["ok"] is False
    assert summary["reason"] == "ledger_unreadable"
    assert preds.read_bytes() == before
