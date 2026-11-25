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


EPOCH_2_NAME = "pre-epoch-2026-01-02T000000Z-bbbbbbbb.json"


def _edit_ledger(tmp_path, edit):
    path = tmp_path / "data" / "predictions.json"
    data = json.loads(path.read_text())
    edit(data)
    path.write_text(json.dumps(data))


def _zero_byte_final(archive, tmp_path):
    (archive / EPOCH_2_NAME).write_bytes(b"")


def _wrong_hash_final(archive, tmp_path):
    (archive / EPOCH_2_NAME).write_bytes(b'{"predictions": [], "resolved": []}')


def _name_is_the_archive_dir(archive, tmp_path):
    _edit_ledger(tmp_path, lambda d: d["epoch_history"][1].update(archive_name=""))


def _name_is_a_parent_file(archive, tmp_path):
    _edit_ledger(tmp_path, lambda d: d["epoch_history"][1].update(archive_name="../predictions.json"))


def _non_dict_receipt(archive, tmp_path):
    _edit_ledger(tmp_path, lambda d: d["epoch_history"].append("not-a-receipt"))


def _non_list_epoch_history(archive, tmp_path):
    _edit_ledger(tmp_path, lambda d: d.update(epoch_history={"reset_request_id": "req-2"}))


def _epoch_history_is(value):
    def corrupt(archive, tmp_path):
        _edit_ledger(tmp_path, lambda d: d.update(epoch_history=value))

    return corrupt


def _symlinked_final(archive, tmp_path):
    decoy = tmp_path / "outside" / "decoy.json"
    decoy.parent.mkdir()
    decoy.write_bytes((archive / ".staging-req-2.json").read_bytes())
    (archive / EPOCH_2_NAME).symlink_to(decoy)


@pytest.mark.parametrize("run_boot", [_worker_boot, _web_boot])
@pytest.mark.parametrize(
    "corrupt",
    [
        _epoch_history_is(None),
        _epoch_history_is(""),
        _epoch_history_is(0),
        _epoch_history_is(False),
        _symlinked_final,
        _zero_byte_final,
        _wrong_hash_final,
        _name_is_the_archive_dir,
        _name_is_a_parent_file,
        _non_dict_receipt,
        _non_list_epoch_history,
    ],
)
def test_boot_keeps_weights_when_published_archive_is_unverified(
    ledger, tmp_path, monkeypatch, caplog, corrupt, run_boot
):
    corrupt(ledger, tmp_path)
    with caplog.at_level(logging.WARNING):
        run_boot(monkeypatch)
    assert weights.load_weights()["quant"] == 1.0
    assert not (tmp_path / "data" / "soul_map.json").exists()
    assert "rebalance skipped" in caplog.text


@pytest.mark.parametrize("run_boot", [_worker_boot, _web_boot])
def test_boot_rebalances_when_published_archive_matches_its_digest(ledger, tmp_path, monkeypatch, run_boot):
    (ledger / ".staging-req-2.json").rename(ledger / EPOCH_2_NAME)
    run_boot(monkeypatch)
    assert round(weights.load_weights()["quant"], 3) == EXPECTED_QUANT_FULL_LEDGER


def test_symlinked_archive_is_reported_unpublished_even_when_target_digest_matches(ledger, tmp_path):
    _symlinked_final(ledger, tmp_path)
    assert ledger_heal.rebalance_blocked_by_unpublished_epochs() is True
    assert ledger_heal.unpublished_epoch_receipts() == ["req-2"]


@pytest.mark.parametrize("value", [None, "", 0, False], ids=["null", "empty-string", "zero", "false"])
def test_present_but_non_list_epoch_history_is_unpublished(ledger, tmp_path, value):
    _epoch_history_is(value)(ledger, tmp_path)
    assert ledger_heal.rebalance_blocked_by_unpublished_epochs() is True
    assert ledger_heal.unpublished_epoch_receipts() == ["<epoch_history is not a list>"]


@pytest.mark.parametrize("run_boot", [_worker_boot, _web_boot])
def test_ledger_without_epoch_history_key_does_not_block_boot(ledger, tmp_path, monkeypatch, run_boot):
    _edit_ledger(tmp_path, lambda d: d.pop("epoch_history"))
    assert ledger_heal.unpublished_epoch_receipts() == []
    assert ledger_heal.rebalance_blocked_by_unpublished_epochs() is False
    run_boot(monkeypatch)
    assert (tmp_path / "data" / "soul_map.json").exists()
