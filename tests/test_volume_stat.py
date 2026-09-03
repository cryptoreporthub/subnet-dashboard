from __future__ import annotations

import json

from internal.ops.volume_stat import WATCH_FILES, build_volume_stat


def test_build_volume_stat_reports_existing_files(tmp_path):
    for name in WATCH_FILES:
        (tmp_path / name).write_text(json.dumps({"ok": True}), encoding="utf-8")

    payload = build_volume_stat(base_dir=tmp_path)

    assert payload["files"]
    assert {entry["path"] for entry in payload["files"]} == {
        str(tmp_path / name) for name in WATCH_FILES
    }
    for entry in payload["files"]:
        assert entry["exists"] is True
        assert entry["mtime_iso"].endswith("Z")
        assert entry["epoch"] > 0
        assert entry["size"] > 0


def test_build_volume_stat_reports_missing_file_honestly(tmp_path):
    payload = build_volume_stat(base_dir=tmp_path)

    assert len(payload["files"]) == len(WATCH_FILES)
    for entry in payload["files"]:
        assert entry["exists"] is False
        assert entry["error"]
        assert entry["mtime_iso"] is None
        assert entry["epoch"] is None
        assert entry["size"] is None
