"""tmp boot reaper — stale .tmp orphans on data volume."""
from __future__ import annotations

import os
import subprocess
import sys
import time


def test_find_stale_tmp_skips_fresh(tmp_path):
    from internal.tmp_boot_reaper import find_stale_tmp_files

    fresh = tmp_path / "live_subnets.json.tmp"
    fresh.write_text("{}", encoding="utf-8")
    assert find_stale_tmp_files(data_dir=str(tmp_path), min_age_seconds=3600) == []


def test_reap_removes_old_generic_tmp_on_sweep(tmp_path, monkeypatch):
    from internal.tmp_boot_reaper import find_stale_tmp_files, reap_stale_tmp_files

    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    old = tmp_path / "stale.json.tmp"
    old.write_text("{}", encoding="utf-8")
    past = time.time() - 7200
    os.utime(old, (past, past))
    keep = tmp_path / "keep.json"
    keep.write_text("{}", encoding="utf-8")

    stale = find_stale_tmp_files(data_dir=str(tmp_path), min_age_seconds=3600, at_boot=False)
    assert str(old) in stale

    count, removed = reap_stale_tmp_files(at_boot=False)
    assert count >= 1
    assert not old.exists()
    assert keep.exists()


def test_boot_skips_generic_sidecar_even_if_old(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUN_MODE", "worker")
    monkeypatch.setenv("TMP_BOOT_REAP", "on")
    monkeypatch.setattr("internal.data_volume.data_dir_is_mounted_volume", lambda: True)
    monkeypatch.setattr("internal.run_mode.inline_worker_expected", lambda: False)
    old = tmp_path / "stale.json.tmp"
    old.write_text("x", encoding="utf-8")
    past = time.time() - 120
    os.utime(old, (past, past))

    from internal.tmp_boot_reaper import maybe_reap_at_boot

    maybe_reap_at_boot()
    assert old.exists()


def test_boot_reaps_dead_pid_sidecar_immediately(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUN_MODE", "worker")
    monkeypatch.setenv("TMP_BOOT_REAP", "on")
    monkeypatch.setattr("internal.data_volume.data_dir_is_mounted_volume", lambda: True)
    monkeypatch.setattr("internal.run_mode.inline_worker_expected", lambda: False)
    code = """
import os, sys, tempfile
d = sys.argv[1]
fd, path = tempfile.mkstemp(dir=d, prefix=f"alerts.json.{os.getpid()}.", suffix=".tmp")
os.write(fd, b"x")
os.close(fd)
print(path)
"""
    proc = subprocess.run(
        [sys.executable, "-c", code, str(tmp_path)],
        capture_output=True,
        text=True,
        check=True,
    )
    sidecar = proc.stdout.strip()
    assert os.path.isfile(sidecar)

    from internal.tmp_boot_reaper import maybe_reap_at_boot

    maybe_reap_at_boot()
    assert not os.path.isfile(sidecar)


def test_find_stale_legacy_mkstemp_json_orphan(tmp_path):
    from internal.tmp_boot_reaper import find_stale_tmp_files

    orphan = tmp_path / "tmpabcd1234.json"
    orphan.write_text("{}", encoding="utf-8")
    past = time.time() - 7200
    os.utime(orphan, (past, past))
    real = tmp_path / "whale_intelligence.json"
    real.write_text("{}", encoding="utf-8")
    os.utime(real, (past, past))

    stale = find_stale_tmp_files(data_dir=str(tmp_path), min_age_seconds=3600, at_boot=False)
    assert str(orphan) in stale
    assert str(real) not in stale


def test_find_stale_legacy_mkstemp_json_orphan_with_underscore(tmp_path):
    from internal.tmp_boot_reaper import find_stale_tmp_files

    orphan = tmp_path / "tmp9x2ly7_l.json"
    orphan.write_text("{}", encoding="utf-8")
    past = time.time() - 7200
    os.utime(orphan, (past, past))

    stale = find_stale_tmp_files(data_dir=str(tmp_path), min_age_seconds=3600, at_boot=False)
    assert str(orphan) in stale


def test_find_stale_legacy_mkstemp_tmp_orphan(tmp_path):
    from internal.tmp_boot_reaper import find_stale_tmp_files

    orphan = tmp_path / "tmpzzzz9999.tmp"
    orphan.write_text("{}", encoding="utf-8")
    past = time.time() - 7200
    os.utime(orphan, (past, past))

    stale = find_stale_tmp_files(data_dir=str(tmp_path), min_age_seconds=3600, at_boot=False)
    assert str(orphan) in stale


def test_reap_skips_when_volume_check_raises(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    old = tmp_path / "stale.json.tmp"
    old.write_text("x", encoding="utf-8")
    past = time.time() - 7200
    os.utime(old, (past, past))
    monkeypatch.setattr(
        "internal.data_volume.data_dir_is_mounted_volume",
        lambda: (_ for _ in ()).throw(RuntimeError("probe failed")),
    )
    from internal.tmp_boot_reaper import maybe_reap_scheduled

    maybe_reap_scheduled()
    assert old.exists()


def test_maybe_reap_at_boot_skips_inline_worker(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUN_MODE", "worker")
    monkeypatch.setenv("TMP_BOOT_REAP", "on")
    monkeypatch.setattr("internal.data_volume.data_dir_is_mounted_volume", lambda: True)
    monkeypatch.setattr("internal.run_mode.inline_worker_expected", lambda: True)
    orphan = tmp_path / "tmpabcd1234.json"
    orphan.write_text("x", encoding="utf-8")
    past = time.time() - 7200
    os.utime(orphan, (past, past))

    from internal.tmp_boot_reaper import maybe_reap_at_boot

    maybe_reap_at_boot()
    assert orphan.exists()


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
