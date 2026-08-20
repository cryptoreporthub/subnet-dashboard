#!/bin/sh
# Fly dedicated worker machine (v2 split) — volume + internal HTTP for web proxy.
# ponytail: single uvicorn process; lifespan starts background workers + live_subnets sync.
set -eu

DEDICATED_BOOT_IMMEDIATE="${LIVE_SUBNETS_BOOT_IMMEDIATE:-off}"

PORT="${WORKER_HTTP_PORT:-8081}"
echo "starting dedicated worker HTTP on :${PORT} (WORKER_HEAVY=${WORKER_HEAVY:-essential}, LIVE_SUBNETS_BOOT_IMMEDIATE=${DEDICATED_BOOT_IMMEDIATE})..."
exec env RUN_MODE=worker \
  WORKER_HEAVY="${WORKER_HEAVY:-essential}" \
  LIVE_SUBNETS_BOOT_IMMEDIATE="${DEDICATED_BOOT_IMMEDIATE}" \
  PUMP_LADDER_BOOT_IMMEDIATE="${PUMP_LADDER_BOOT_IMMEDIATE:-off}" \
  LIVE_SUBNETS_FETCH_MODE="${LIVE_SUBNETS_FETCH_MODE:-lite}" \
  MESSAGE_INTEL_LISTENER="${MESSAGE_INTEL_LISTENER:-on}" \
  TELEGRAM_GROUP_ID="${TELEGRAM_GROUP_ID:-}" \
  uvicorn server:app --host 0.0.0.0 --port "$PORT"
