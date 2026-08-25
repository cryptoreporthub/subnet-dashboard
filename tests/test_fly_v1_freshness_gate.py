"""Regression checks for the worker-aware v1 Fly freshness gate."""

from __future__ import annotations

import os
import stat
import subprocess
from datetime import datetime, timezone
from pathlib import Path


def _write_mock_curl(tmp_path, *, worker_alive: bool) -> None:
    now = datetime.now(timezone.utc).isoformat()
    mock_curl = tmp_path / "curl"
    mock_curl.write_text(
        f"""#!/usr/bin/env bash
args="$*"
out=""
format=0
while [ "$#" -gt 0 ]; do
  case "$1" in
    -o) out="$2"; shift 2; continue ;;
    -w) format=1; shift 2; continue ;;
  esac
  shift
done
if [[ "$args" == *"/api/learning/health"* ]]; then
  payload='{{"status":"ok","resolver":{{"running":true,"last_ok":true}},"last_resolver_tick":"{now}","pick_scheduler":{{"daily":{{"last_run_ok":true,"last_run_error":null}},"last_tick":{{"ok":true}}}},"daily_pick":{{"reason":null}}}}'
  if [ -n "$out" ]; then printf '%s' "$payload" > "$out"; fi
  if [ "$format" = "1" ]; then printf '200 0.001'; elif [ -z "$out" ]; then printf '%s' "$payload"; fi
elif [[ "$args" == *"/health"* ]]; then
  printf '200'
elif [[ "$args" == *"/api/ops/readiness"* ]]; then
  printf '%s' '{{"worker_mode":"split","status":"ready","worker_peer":{{"alive":{str(worker_alive).lower()}}}}}'
elif [[ "$args" == *"/api/data-freshness"* ]]; then
  printf '%s' '{{"stale":false,"subnet_count":146,"last_sync":"2026-08-25T00:00:00Z","age_seconds":1}}'
elif [[ "$args" == *"/metrics"* ]]; then
  printf '%s' 'subnet_sync_last_ok 0.0'
fi
""",
        encoding="utf-8",
    )
    mock_curl.chmod(mock_curl.stat().st_mode | stat.S_IEXEC)


def _run_gate(tmp_path, *, worker_alive: bool):
    _write_mock_curl(tmp_path, worker_alive=worker_alive)
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
    return result


def test_gate_rejects_zero_sync_metric_without_live_worker(tmp_path):
    """A fresh-looking cache cannot mask a dead inline worker."""
    result = _run_gate(tmp_path, worker_alive=False)

    assert result.returncode != 0
    assert "worker-backed sync path unhealthy" in result.stdout


def test_gate_accepts_web_local_zero_when_worker_backed_cache_is_healthy(tmp_path):
    result = _run_gate(tmp_path, worker_alive=True)

    assert result.returncode == 0
    assert "web-local; worker heartbeat and shared cache are healthy" in result.stdout