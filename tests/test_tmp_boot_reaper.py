"""tmp boot reaper — stale .tmp orphans on data volume."""
from __future__ import annotations

import os
import time


def test_find_stale_tmp_skips_fresh(tmp_path):
    from internal.tmp_boot_reaper import find_stale_tmp_files

    fresh = tmp_path / "live_subnets.json.tmp"
    fresh.write_text("{}", encoding="utf-8")
    assert find_stale_tmp_files(data_dir=str(tmp_path), min_age_seconds=3600) == []


def test_reap_removes_old_tmp_only(tmp_path, monkeypatch):
    from internal.tmp_boot_reaper import find_stale_tmp_files, reap_stale_tmp_files

    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    old = tmp_path / "stale.json.tmp"
    old.write_text("{}", encoding="utf-8")
    past = time.time() - 7200
    os.utime(old, (past, past))
    keep = tmp_path / "keep.json"
    keep.write_text("{}", encoding="utf-8")

    stale = find_stale_tmp_files(data_dir=str(tmp_path), min_age_seconds=3600)
    assert str(old) in stale

    count, removed = reap_stale_tmp_files()
    assert count >= 1
    assert not old.exists()
    assert keep.exists()


def test_find_stale_legacy_mkstemp_json_orphan(tmp_path):
    from internal.tmp_boot_reaper import find_stale_tmp_files

    orphan = tmp_path / "tmpabcd1234.json"
    orphan.write_text("{}", encoding="utf-8")
    past = time.time() - 7200
    os.utime(orphan, (past, past))
    real = tmp_path / "whale_intelligence.json"
    real.write_text("{}", encoding="utf-8")
    os.utime(real, (past, past))

    stale = find_stale_tmp_files(data_dir=str(tmp_path), min_age_seconds=3600)
    assert str(orphan) in stale
    assert str(real) not in stale


def test_find_stale_legacy_mkstemp_json_orphan_with_underscore(tmp_path):
    from internal.tmp_boot_reaper import find_stale_tmp_files

    orphan = tmp_path / "tmp9x2ly7_l.json"
    orphan.write_text("{}", encoding="utf-8")
    past = time.time() - 7200
    os.utime(orphan, (past, past))

    stale = find_stale_tmp_files(data_dir=str(tmp_path), min_age_seconds=3600)
    assert str(orphan) in stale


def test_find_stale_legacy_mkstemp_tmp_orphan(tmp_path):
    from internal.tmp_boot_reaper import find_stale_tmp_files

    orphan = tmp_path / "tmpzzzz9999.tmp"
    orphan.write_text("{}", encoding="utf-8")
    past = time.time() - 7200
    os.utime(orphan, (past, past))

    stale = find_stale_tmp_files(data_dir=str(tmp_path), min_age_seconds=3600)
    assert str(orphan) in stale


def test_maybe_reap_at_boot_reaps_fresh_orphans(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUN_MODE", "worker")
    monkeypatch.setenv("TMP_BOOT_REAP", "on")
    monkeypatch.setattr(
        "internal.data_volume.data_dir_is_mounted_volume",
        lambda: True,
    )
    fresh = tmp_path / "stale.json.tmp"
    fresh.write_text("x", encoding="utf-8")

    from internal.tmp_boot_reaper import maybe_reap_at_boot

    maybe_reap_at_boot()
    assert not fresh.exists()


def test_maybe_reap_at_boot_skips_non_worker(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUN_MODE", "web")
    monkeypatch.setenv("TMP_BOOT_REAP", "on")
    old = tmp_path / "x.json.tmp"
    old.write_text("x", encoding="utf-8")
    past = time.time() - 7200
    os.utime(old, (past, past))

    from internal.tmp_boot_reaper import maybe_reap_at_boot

    maybe_reap_at_boot()
    assert old.exists()
