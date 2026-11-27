"""A ledger write must be durable before it is renamed into place.

main wrote predictions.json through safe_write_json, which fsyncs the temp file and
the directory. The unlocked writer dropped both, so a power cut after the rename can
leave a zero-length or partial ledger. This test records the order of fsync and
rename calls during one ledger write.
"""

from __future__ import annotations

import json
import os
import stat

from internal.learning import predictions_store


def _fd_kind(fd):
    """Return 'file:<name>' for a regular file, 'dir' for a directory."""
    mode = os.fstat(fd).st_mode
    if stat.S_ISDIR(mode):
        return "dir"
    return "file"


def test_ledger_write_fsyncs_temp_before_rename_and_fsyncs_dir(tmp_path, monkeypatch):
    path = tmp_path / "predictions.json"
    path.write_text(json.dumps({"predictions": [], "resolved": [], "stats": {}}))
    events = []

    real_fsync = os.fsync
    real_replace = os.replace

    def record_fsync(fd):
        events.append(("fsync", _fd_kind(fd)))
        return real_fsync(fd)

    def record_replace(src, dst):
        events.append(("replace", str(dst)))
        return real_replace(src, dst)

    monkeypatch.setattr(os, "fsync", record_fsync)
    monkeypatch.setattr(os, "replace", record_replace)

    predictions_store._write_predictions_unlocked(
        {"predictions": [{"id": "r1"}], "resolved": [], "stats": {}},
        path=str(path),
    )

    rename_at = next(i for i, (kind, _) in enumerate(events) if kind == "replace")
    file_syncs_before = [i for i, (k, v) in enumerate(events) if k == "fsync" and v == "file" and i < rename_at]
    dir_syncs_after = [i for i, (k, v) in enumerate(events) if k == "fsync" and v == "dir" and i > rename_at]
    assert file_syncs_before, f"temp file not fsynced before rename: {events}"
    assert dir_syncs_after, f"directory not fsynced after rename: {events}"
    assert json.loads(path.read_text())["predictions"] == [{"id": "r1"}]
