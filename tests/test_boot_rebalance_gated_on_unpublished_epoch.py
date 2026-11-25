"""A boot must not save council weights while an epoch archive is still unpublished."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from unittest.mock import MagicMock

import pytest

import internal.background_boot as background_boot
import internal.learning.ledger_heal as ledger_heal
from internal.council import weights

EXPECTED_QUANT_FULL_LEDGER = 1.084


def _row(i, ok):
    return {
        "id": f"r{i}", "netuid": 1,
        "created_at": f"2026-01-01T00:{i:02d}:00", "resolved_at": f"2026-01-02T00:{i:02d}:00",
        "correct": ok, "outcome": "hit" if ok else "miss",
        "signal_impact": {"dominant": "emission_momentum"},
    }


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    """Epoch 1 is published (6 misses). Epoch 2 (15 hits) exists only as a staging file."""
    from internal.store import soul_map_io

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(soul_map_io, "_cache", {})
    archive = tmp_path / "data" / "predictions_archive"
    archive.mkdir(parents=True)
    monkeypatch.setenv("RUN_MODE", "worker")
    monkeypatch.delenv("COUNCIL_WEIGHT_REBALANCE_ON_BOOT", raising=False)
    monkeypatch.setattr(ledger_heal, "ARCHIVE_DIR", str(archive))
    monkeypatch.setattr(weights, "PREDICTIONS_ARCHIVE_DIR", str(archive))

    published = json.dumps({"predictions": [], "resolved": [_row(i, False) for i in range(6)]}).encode()
    staged = json.dumps({"predictions": [], "resolved": [_row(100 + i, True) for i in range(15)]}).encode()
    name1, name2 = "pre-epoch-2026-01-01T000000Z-aaaaaaaa.json", "pre-epoch-2026-01-02T000000Z-bbbbbbbb.json"
    (archive / name1).write_bytes(published)
    (archive / ".staging-req-2.json").write_bytes(staged)
    (tmp_path / "data" / "predictions.json").write_text(json.dumps({
        "predictions": [], "resolved": [],
        "epoch_history": [
            {"reset_request_id": "req-1", "archive_name": name1, "archive_sha256": _sha(published)},
            {"reset_request_id": "req-2", "archive_name": name2, "archive_sha256": _sha(staged)},
        ],
    }))
    return archive


def _boot(monkeypatch, reconcile):
    class _InlineThread:
        def __init__(self, target=None, **_kwargs):
            self._target = target

        def start(self):
            self._target()

    monkeypatch.setattr(background_boot.threading, "Thread", _InlineThread)
    monkeypatch.setattr(background_boot, "defer_boot", lambda _name, fn, delay=0: fn())
    monkeypatch.setattr(
        "internal.council.resolver_scheduler.start_prediction_resolver_scheduler",
        MagicMock(return_value={}),
    )
    monkeypatch.setattr(
        "internal.council.resolver_scheduler.maybe_status_aware_resolver_revive_on_boot",
        MagicMock(return_value={}),
    )
    monkeypatch.setattr(ledger_heal, "heal_daily_pick_ledger", MagicMock(return_value={"ok": True}))
    monkeypatch.setattr(
        "internal.learning.pump_lead_recover.recover_overdue_pump_leads",
        MagicMock(return_value={"ok": True}),
    )
    monkeypatch.setattr(ledger_heal, "reconcile_epoch_archives", reconcile)
    background_boot._start_resolver()


def _raises():
    raise OSError(28, "No space left on device")


@pytest.mark.parametrize("failing_reconcile", [_raises, lambda: {"ok": False, "reason": "archive_publish_failed"}])
def test_boot_keeps_weights_until_staged_epoch_is_published(ledger, monkeypatch, failing_reconcile):
    assert weights.load_weights()["quant"] == 1.0

    _boot(monkeypatch, failing_reconcile)
    assert weights.load_weights()["quant"] == 1.0

    _boot(monkeypatch, _real_reconcile)
    assert sorted(p.name for p in ledger.iterdir() if p.name.startswith("pre-epoch-")) == [
        "pre-epoch-2026-01-01T000000Z-aaaaaaaa.json",
        "pre-epoch-2026-01-02T000000Z-bbbbbbbb.json",
    ]
    assert round(weights.load_weights()["quant"], 3) == EXPECTED_QUANT_FULL_LEDGER


def test_boot_rebalances_when_every_receipt_is_published(ledger, monkeypatch):
    _boot(monkeypatch, _real_reconcile)
    assert round(weights.load_weights()["quant"], 3) == EXPECTED_QUANT_FULL_LEDGER


_real_reconcile = ledger_heal.reconcile_epoch_archives


def test_web_boot_thread_keeps_weights_until_staged_epoch_is_published(ledger, monkeypatch):
    import server

    monkeypatch.setattr(time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(ledger_heal, "reconcile_epoch_archives", _raises)
    server._council_weight_rebalance_boot()
    assert weights.load_weights()["quant"] == 1.0

    _real_reconcile()
    server._council_weight_rebalance_boot()
    assert round(weights.load_weights()["quant"], 3) == EXPECTED_QUANT_FULL_LEDGER


def _worker_boot(monkeypatch):
    _boot(monkeypatch, _real_reconcile)


def _web_boot(monkeypatch):
    import server

    monkeypatch.setattr(time, "sleep", lambda _seconds: None)
    server._council_weight_rebalance_boot()


@pytest.mark.parametrize("run_boot", [_worker_boot, _web_boot])
def test_boot_writes_nothing_when_ledger_is_unreadable(ledger, tmp_path, monkeypatch, caplog, run_boot):
    (tmp_path / "data" / "predictions.json").write_text("{torn")
    with caplog.at_level(logging.WARNING):
        run_boot(monkeypatch)
    assert not (tmp_path / "data" / "soul_map.json").exists()
    assert "rebalance skipped" in caplog.text and "unreadable" in caplog.text
