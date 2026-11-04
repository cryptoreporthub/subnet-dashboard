#!/usr/bin/env bash
# Run one agent-sdk eval slot with enforceable wall cap (kill process group on stall).
# Prints exit code to stdout; logs stall/timeout lines to RUN_LOG via caller tee.
set -euo pipefail

BOT="${1:?bot dir}"
EVAL_ID="${2:?eval id}"
STATE="${3:?state root}"
OUT_JSON="${4:?out json path}"
METHOD_ARM="${5:?R2_METHOD_ARM}"
SLOT_WALL_SEC="${6:-900}"
RUN_LOG="${7:-/dev/stderr}"

HERMETIC=(env -i HOME="$HOME" PATH="$PATH" USER="${USER:-ubuntu}" TMPDIR="${TMPDIR:-/tmp}"
  CURSOR_API_KEY="${CURSOR_API_KEY:?CURSOR_API_KEY required}" R2_METHOD_ARM="$METHOD_ARM")

START_EPOCH="$(date +%s)"
echo "LOOP_STALL_GUARD start_epoch=${START_EPOCH} slot_wall_s=${SLOT_WALL_SEC} eval_id=${EVAL_ID}" >>"$RUN_LOG"

set +e
setsid "${HERMETIC[@]}" bash -lc \
  "cd $(printf '%q' "$BOT") && exec npx agent-sdk eval --dir . $(printf '%q' "$EVAL_ID") --json --no-stream --max-concurrency 1 --state-root $(printf '%q' "$STATE") --out $(printf '%q' "$OUT_JSON")" \
  >>"$RUN_LOG" 2>&1 &
EVAL_PID=$!
EVAL_PGID="$(ps -o pgid= -p "$EVAL_PID" 2>/dev/null | tr -d ' ')"
EC=0

while kill -0 "$EVAL_PID" 2>/dev/null; do
  NOW="$(date +%s)"
  ELAPSED=$((NOW - START_EPOCH))
  if (( ELAPSED >= SLOT_WALL_SEC )); then
    echo "slot_timeout=1 stall_guard kill pid=${EVAL_PID} pgid=${EVAL_PGID} elapsed_s=${ELAPSED} eval_id=${EVAL_ID}" >>"$RUN_LOG"
    if [[ -n "${EVAL_PGID:-}" ]]; then
      kill -TERM -- "-${EVAL_PGID}" 2>/dev/null || true
    fi
    kill -TERM "$EVAL_PID" 2>/dev/null || true
    sleep 5
    if [[ -n "${EVAL_PGID:-}" ]]; then
      kill -KILL -- "-${EVAL_PGID}" 2>/dev/null || true
    fi
    kill -KILL "$EVAL_PID" 2>/dev/null || true
    wait "$EVAL_PID" 2>/dev/null || true
    EC=124
    break
  fi
  sleep 15
done

if (( EC == 0 )); then
  wait "$EVAL_PID"
  EC=$?
  if (( EC == 137 || EC == 143 )); then
    EC=124
  fi
fi
set -e
echo "$EC"
