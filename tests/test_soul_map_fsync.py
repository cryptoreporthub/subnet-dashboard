"""A soul-map write must be durable before it is renamed into place.

The write path replaced the file without fsync. A power cut after the rename can
leave an empty soul map, and the zero-byte rule then treats it as missing and
reseeds it. This test records the order of fsync and rename calls for one write.
"""

from __future__ import annotations

import json
import os
import stat

from internal.store import soul_map_io


def _fd_kind(fd):
    return "dir" if stat.S_ISDIR(os.fstat(fd).st_mode) else "file"


def test_soul_map_write_fsyncs_temp_before_rename_and_dir_after(tmp_path, monkeypatch):
    path = tmp_path / "soul_map.json"
    path.write_text(json.dumps({"adversarial_state": {}}))
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

    def mutate(blob):
        blob["judge_weights"] = {"oracle": 0.4}

    result = soul_map_io.write_soul_map(mutate, str(path))

    assert result.outcome is soul_map_io.WriteOutcome.APPLIED
    replace_at = events.index(("replace", str(path)))
    assert ("fsync", "file") in events[:replace_at], f"temp file not fsynced before rename: {events}"
    assert ("fsync", "dir") in events[replace_at + 1:], f"directory not fsynced after rename: {events}"
