"""Snapshot test suites must not write into the repo's tracked data/ directory."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

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
