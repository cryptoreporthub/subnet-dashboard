"""POST /api/learning/rebalance-weights must not persist weights while an epoch archive is unpublished."""

from __future__ import annotations

import hashlib
import json

import pytest
from fastapi.testclient import TestClient

import internal.learning.ledger_heal as ledger_heal
from internal.council import weights

from tests.test_boot_rebalance_gated_on_unpublished_epoch import (  # noqa: F401  (ledger is a fixture)
    EXPECTED_QUANT_FULL_LEDGER,
    ledger,
)

URL = "/api/learning/rebalance-weights"


@pytest.fixture
def client():
    import server

    return TestClient(server.app)


def test_manual_rebalance_refused_while_epoch_unpublished(ledger, tmp_path, client):
    resp = client.post(URL)
    assert resp.status_code == 409
    assert "epoch_archive_unpublished" in json.dumps(resp.json())
    assert not (tmp_path / "data" / "soul_map.json").exists()
    assert weights.load_weights()["quant"] == 1.0


def test_manual_rebalance_dry_run_still_answers_while_epoch_unpublished(ledger, tmp_path, client):
    resp = client.post(URL, params={"dry_run": "true"})
    assert resp.status_code == 200
    assert not (tmp_path / "data" / "soul_map.json").exists()


def test_manual_rebalance_saves_when_every_receipt_is_published(ledger, client):
    (ledger / ".staging-req-2.json").rename(ledger / "pre-epoch-2026-01-02T000000Z-bbbbbbbb.json")
    resp = client.post(URL)
    assert resp.status_code == 200
    assert round(weights.load_weights()["quant"], 3) == EXPECTED_QUANT_FULL_LEDGER


@pytest.mark.parametrize("bad_name", ["not-an-archive.json", "../outside.json"])
def test_archive_name_that_fails_the_writer_pattern_is_unpublished(tmp_path, bad_name):
    archive = tmp_path / "archive"
    archive.mkdir()
    raw = b'{"predictions": [], "resolved": []}'
    (tmp_path / "outside.json").write_bytes(raw)
    (archive / "not-an-archive.json").write_bytes(raw)
    ledger_path = tmp_path / "predictions.json"
    ledger_path.write_text(json.dumps({
        "predictions": [], "resolved": [],
        "epoch_history": [{
            "reset_request_id": "req-bad",
            "archive_name": bad_name,
            "archive_sha256": hashlib.sha256(raw).hexdigest(),
        }],
    }))
    assert ledger_heal.unpublished_epoch_receipts(
        predictions_path=str(ledger_path), archive_dir=str(archive)
    ) == ["req-bad"]
