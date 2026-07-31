#!/usr/bin/env bash
# split_v2 web → worker: prefer flycast :8081 (survives machine recreate).
# Unset machine-specific WORKER_INTERNAL_URL — stale 6PN IPs wedge every proxy ~12s.
set -euo pipefail

APP="${FLY_APP:-subnet-dashboard}"
PORT="${WORKER_HTTP_PORT:-8081}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

if ! "$SCRIPT_DIR/fly_worker_split_v2_guard.sh"; then
  echo "fly_set_worker_internal_url: split_v2 not enabled — unset legacy WORKER_INTERNAL_URL"
  flyctl secrets unset WORKER_INTERNAL_URL --app "$APP" 2>/dev/null || true
  exit 0
fi

echo "fly_set_worker_internal_url: unset machine-specific WORKER_INTERNAL_URL (use flycast :${PORT})"
flyctl secrets unset WORKER_INTERNAL_URL --app "$APP" 2>/dev/null || true
