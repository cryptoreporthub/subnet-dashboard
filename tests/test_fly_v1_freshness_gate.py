"""Regression checks for the worker-aware v1 Fly freshness gate."""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path


def test_gate_rejects_zero_sync_metric_without_live_worker(tmp_path):
    """A fresh-looking cache cannot mask a dead inline worker."""
    mock_curl = tmp_path / "curl"
    mock_curl.write_text(
        """#!/usr/bin/env bash
args="$*"
if [[ "$args" == *"/health"* ]]; then
  printf '200'
elif [[ "$args" == *"/api/ops/readiness"* ]]; then
  printf '%s' '{"worker_mode":"split","status":"ready","worker_peer":{"alive":false}}'
elif [[ "$args" == *"/api/data-freshness"* ]]; then
  printf '%s' '{"stale":false,"subnet_count":146,"last_sync":"2026-08-25T00:00:00Z","age_seconds":1}'
elif [[ "$args" == *"/metrics"* ]]; then
  printf '%s' 'subnet_sync_last_ok 0.0'
fi
""",
        encoding="utf-8",
    )
    mock_curl.chmod(mock_curl.stat().st_mode | stat.S_IEXEC)

    env = {
        **os.environ,
        "PATH": f"{tmp_path}:{os.environ['PATH']}",
        "APP_BASE_URL": "https://example.invalid",
        "FRESHNESS_WAIT_SECONDS": "1",
        "FRESHNESS_INTERVAL_SECONDS": "1",
    }
    result = subprocess.run(
        ["bash", "scripts/fly_v1_freshness_gate.sh"],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "worker-backed sync path unhealthy" in result.stdout