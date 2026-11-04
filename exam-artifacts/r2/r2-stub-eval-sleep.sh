#!/usr/bin/env bash
# Stub eval for stall-guard repro: long sleep + continuous stdout (simulates eval log flood).
set -euo pipefail
SEC="${1:-3600}"
for (( i = 1; i <= SEC; i++ )); do
  echo "stub_eval_log_line=${i} ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  sleep 1
done
