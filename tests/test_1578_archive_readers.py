import hashlib
import json

from internal.accuracy_lift.measure import load_archive


def test_archive_reader_reports_bad_file_and_keeps_valid_legacy_and_new(tmp_path):
    legacy = tmp_path / "pre-epoch-2026-08-18T120000Z"
    newer = tmp_path / "pre-epoch-2026-08-18T120000Z-12345678.json"
    broken = tmp_path / "pre-epoch-2026-08-18T120001Z"
    legacy.write_text(json.dumps({"resolved": [{"id": "legacy"}]}))
    newer.write_text(json.dumps({"resolved": [{"id": "new"}]}))
    broken.write_text("{broken")
    (tmp_path / "pre-epoch-2026-08-18T120002Z.partial").write_text("{partial")
    (tmp_path / ".staging-123.json").write_text("{partial")
    result = load_archive(str(tmp_path))
    assert [row["id"] for row in result["resolved"]] == ["legacy", "new"]
    assert any("pre-epoch-2026-08-18T120001Z" in str(err) for err in result["archive_errors"])
    assert len(result["archive_errors"]) == 1


def test_archive_reader_ignores_staging_and_partial_files(tmp_path):
    legacy = tmp_path / "pre-epoch-2026-08-18T120000Z"
    legacy.write_text(json.dumps({"resolved": [{"id": "legacy"}]}))
    (tmp_path / "pre-epoch-2026-08-18T120000Z.partial").write_text("{partial")
    (tmp_path / ".staging-request.json").write_text("{partial")
    result = load_archive(str(tmp_path))
    assert result["archive_files"] == [legacy.name]
    assert result.get("archive_errors", []) == []


def test_measure_script_exits_nonzero_when_an_archive_is_corrupt(tmp_path, monkeypatch):
    import sys
    from scripts.measure_accuracy_archive import main

    (tmp_path / "pre-epoch-2026-08-18T120000Z").write_text(json.dumps({"resolved": []}))
    (tmp_path / "pre-epoch-2026-08-18T120001Z").write_text("{broken")
    monkeypatch.setattr(sys, "argv", [
        "measure_accuracy_archive.py", "--archive", str(tmp_path),
        "--out-json", str(tmp_path / "summary.json"), "--out-md", str(tmp_path / "summary.md"),
    ])
    try:
        status = main()
    except Exception as exc:
        raise AssertionError("corrupt archive was not reported cleanly") from exc
    assert status != 0


def test_replay_warns_and_keeps_rows_from_valid_archive(tmp_path, caplog):
    from internal.council.weights import _archive_replay_rows

    (tmp_path / "pre-epoch-2026-08-18T120000Z").write_text(json.dumps({
        "resolved": [{"id": "valid", "correct": True, "outcome": "hit"}],
    }))
    (tmp_path / "pre-epoch-2026-08-18T120001Z").write_text("{broken")
    rows = _archive_replay_rows(str(tmp_path))
    assert [row["id"] for row in rows] == ["valid"]
    assert "pre-epoch-2026-08-18T120001Z" in caplog.text


def test_single_corrupt_archive_reports_error_without_crashing(tmp_path):
    broken = tmp_path / "pre-epoch-2026-08-18T120001Z"
    broken.write_text("{broken")
    result = load_archive(str(broken))
    assert result["resolved"] == []
    assert result["archive_errors"][0]["file"] == broken.name


def test_one_bad_epoch_receipt_does_not_block_later_epochs(tmp_path):
    """A missing archive for an older epoch must not stop a newer staged archive from publishing."""
    from internal.learning import ledger_heal, predictions_store

    dest = tmp_path / "archives"
    dest.mkdir()
    newer = b'{"predictions": [], "resolved": []}'
    newer_sha = hashlib.sha256(newer).hexdigest()
    (dest / ".staging-r2.json").write_bytes(newer)
    ledger = tmp_path / "predictions.json"
    ledger.write_text(json.dumps({
        "predictions": [], "resolved": [], "stats": {},
        "epoch_history": [
            {"reset_request_id": "r1", "archive_name": "pre-epoch-old.json", "archive_sha256": "0" * 64},
            {"reset_request_id": "r2", "archive_name": "pre-epoch-new.json", "archive_sha256": newer_sha},
        ],
    }))

    result = ledger_heal.reconcile_epoch_archives(predictions_path=str(ledger), archive_dir=str(dest))

    assert (dest / "pre-epoch-new.json").read_bytes() == newer, "newer epoch was not published"
    assert result["ok"] is False
    assert [f["reset_request_id"] for f in result["failures"]] == ["r1"]
