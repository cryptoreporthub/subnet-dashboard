"""Snapshot test suites must not write into the repo's tracked data/ directory."""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
LEAK = REPO / "data" / "score_snapshot_cycle.json"


def test_coverage_integration_suite_does_not_write_the_cycle_receipt_into_repo_data():
    had_file = LEAK.exists()
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/test_score_snapshot_coverage_integration.py",
            "-q",
            "-p",
            "no:cacheprovider",
        ],
        cwd=REPO,
        env={**os.environ, "DISABLE_BACKGROUND_SCANS": "1"},
        capture_output=True,
        text=True,
    )
    leaked = LEAK.exists() and not had_file
    if leaked:
        LEAK.unlink()
    assert proc.returncode == 0, proc.stdout[-2000:]
    assert not leaked


# --- every data/ file, by content hash (git status misses gitignored files such as soul_map.json) ---

DATA = REPO / "data"
SNAPSHOT_SUITES = (
    "tests/test_snapshot_membership_provenance.py",
    "tests/test_score_snapshot*.py",
    "tests/test_subnet_universe.py",
    "tests/test_universe_stale_stamp.py",
    "tests/test_seed_build_restores_process_state.py",
    "tests/test_snapshot_coverage.py",
    "tests/test_committed_seed.py",
    "tests/test_check_score_snapshot_seed.py",
    "tests/test_scorer_identity.py",
    "tests/test_served_snapshot_reason.py",
    "tests/test_volume_fresh_snapshot_gate.py",
    "tests/test_receipt_chain_negative_proof.py",
    "tests/test_weights_digest_path_anchor.py",
    "tests/test_chain_read.py",
)


def _suite_files() -> list:
    found = {str(p.relative_to(REPO)) for pattern in SNAPSHOT_SUITES for p in REPO.glob(pattern)}
    return sorted(found)


def data_hashes(root: Path = DATA) -> dict:
    """Relative path -> sha256 for every file under ``root``.

    SQLite databases and their -wal/-shm sidecars are skipped: opening one in WAL mode rewrites the
    sidecars without changing any data.
    """
    out = {}
    for path in sorted(root.rglob("*")):
        if path.is_file() and ".db" not in path.name:
            out[str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
    return out


def changed_files(before: dict, after: dict) -> list:
    return sorted(name for name in set(before) | set(after) if before.get(name) != after.get(name))


def test_changed_files_reports_edits_additions_and_removals(tmp_path):
    (tmp_path / "keep.json").write_text("1")
    (tmp_path / "edit.json").write_text("1")
    (tmp_path / "gone.json").write_text("1")
    (tmp_path / "cache.db-wal").write_text("x")
    before = data_hashes(tmp_path)
    (tmp_path / "edit.json").write_text("2")
    (tmp_path / "gone.json").unlink()
    (tmp_path / "new.json").write_text("1")
    (tmp_path / "cache.db-wal").write_text("y")
    assert changed_files(before, data_hashes(tmp_path)) == ["edit.json", "gone.json", "new.json"]


@pytest.mark.skipif(
    os.environ.get("RUN_SLOW_DATA_CLEAN") != "1",
    reason="slow: runs every snapshot suite in a subprocess; set RUN_SLOW_DATA_CLEAN=1",
)
def test_snapshot_suites_leave_every_data_file_unchanged():
    before = data_hashes()
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", *_suite_files(), "-q", "-p", "no:cacheprovider"],
        cwd=REPO,
        env={**os.environ, "DISABLE_BACKGROUND_SCANS": "1"},
        capture_output=True,
        text=True,
    )
    # This test is about data/, not about the suites' own results: 0 or 1 means they ran to the end.
    assert proc.returncode in (0, 1), proc.stdout[-2000:]
    assert changed_files(before, data_hashes()) == []
