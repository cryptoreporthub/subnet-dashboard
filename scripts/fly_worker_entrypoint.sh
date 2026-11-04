#!/bin/sh
# Fly dedicated worker machine (v2 split) — volume + internal HTTP for web proxy.
# ponytail: single uvicorn process; lifespan starts background workers + live_subnets sync.
set -eu

# ARENA-CAP TOGGLE (memory fix 1, #1538): default ON (=2) for capture 2. Change -2 to - to turn the default off. Env override wins (set it EMPTY to turn the cap off without a code change); non-numeric values are ignored.
WORKER_MALLOC_ARENA_MAX="${WORKER_MALLOC_ARENA_MAX-2}"
# Validation MUST run before the ${VAR:+MALLOC_ARENA_MAX=$VAR} expansion below: the expansion is unquoted, so an unvalidated value would word-split into extra env args.
case "$WORKER_MALLOC_ARENA_MAX" in "") ;; *[!0-9]*|0*) echo "ignoring invalid WORKER_MALLOC_ARENA_MAX (need 1-9 then digits)" >&2; WORKER_MALLOC_ARENA_MAX="" ;; esac
DEDICATED_BOOT_IMMEDIATE="${LIVE_SUBNETS_BOOT_IMMEDIATE:-off}"

PORT="${WORKER_HTTP_PORT:-8081}"
echo "starting dedicated worker HTTP on :${PORT} (WORKER_HEAVY=${WORKER_HEAVY:-essential}, LIVE_SUBNETS_BOOT_IMMEDIATE=${DEDICATED_BOOT_IMMEDIATE})..."
exec env RUN_MODE=worker \
  ${WORKER_MALLOC_ARENA_MAX:+MALLOC_ARENA_MAX=${WORKER_MALLOC_ARENA_MAX}} \
  WORKER_HEAVY="${WORKER_HEAVY:-essential}" \
  LIVE_SUBNETS_BOOT_IMMEDIATE="${DEDICATED_BOOT_IMMEDIATE}" \
  PUMP_LADDER_BOOT_IMMEDIATE="${PUMP_LADDER_BOOT_IMMEDIATE:-off}" \
  LIVE_SUBNETS_FETCH_MODE="${LIVE_SUBNETS_FETCH_MODE:-lite}" \
  MESSAGE_INTEL_LISTENER="${MESSAGE_INTEL_LISTENER:-on}" \
  TELEGRAM_GROUP_ID="${TELEGRAM_GROUP_ID:-}" \
  uvicorn server:app --host 0.0.0.0 --port "$PORT"
