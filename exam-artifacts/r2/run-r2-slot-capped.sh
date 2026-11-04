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
ART="$(cd "$(dirname "$0")" && pwd)"
STUB_SLEEP="${ART}/r2-stub-eval-sleep.sh"
STUB_IGNORE="${ART}/r2-stub-eval-ignore-term.sh"

if [[ "${R2_REPRO_STUB_EVAL:-}" == "1" || "${R2_REPRO_STUB_EVAL:-}" == "2" ]]; then
  HERMETIC=(env -i HOME="$HOME" PATH="$PATH" USER="${USER:-ubuntu}" TMPDIR="${TMPDIR:-/tmp}"
    CURSOR_API_KEY="${CURSOR_API_KEY:-repro-stub}" R2_METHOD_ARM="$METHOD_ARM")
else
  HERMETIC=(env -i HOME="$HOME" PATH="$PATH" USER="${USER:-ubuntu}" TMPDIR="${TMPDIR:-/tmp}"
    CURSOR_API_KEY="${CURSOR_API_KEY:?CURSOR_API_KEY required}" R2_METHOD_ARM="$METHOD_ARM")
fi

START_EPOCH="$(date +%s)"
echo "LOOP_STALL_GUARD start_epoch=${START_EPOCH} slot_wall_s=${SLOT_WALL_SEC} eval_id=${EVAL_ID}" >>"$RUN_LOG"

if [[ "${R2_REPRO_STUB_EVAL:-}" == "2" ]]; then
  EVAL_CMD=(bash -lc "exec env R2_STUB_MARKER=\"${R2_STUB_MARKER:-stub_ignore_term}\" bash $(printf '%q' "$STUB_IGNORE")")
elif [[ "${R2_REPRO_STUB_EVAL:-}" == "1" ]]; then
  EVAL_CMD=(bash -lc "exec bash $(printf '%q' "$STUB_SLEEP") 3600")
else
  EVAL_CMD=(bash -lc "cd $(printf '%q' "$BOT") && exec npx agent-sdk eval --dir . $(printf '%q' "$EVAL_ID") --json --no-stream --max-concurrency 1 --state-root $(printf '%q' "$STATE") --out $(printf '%q' "$OUT_JSON")")
fi

# Eval: setsid session + PG backstop watchdog at SLOT_WALL_SEC; timeout tail --pid backstop (+60s).

set +e
setsid "${HERMETIC[@]}" "${EVAL_CMD[@]}" >>"$RUN_LOG" 2>&1 &
EVAL_PID=$!
EVAL_PGID="$(ps -o pgid= -p "$EVAL_PID" 2>/dev/null | tr -d ' ')"

EC=0
DEADLINE_EPOCH=$((START_EPOCH + SLOT_WALL_SEC))
while kill -0 "$EVAL_PID" 2>/dev/null; do
  if (( $(date +%s) >= DEADLINE_EPOCH )); then
    NOW="$(date +%s)"
    ELAPSED=$((NOW - START_EPOCH))
    echo "slot_timeout=1 stall_guard pg_backstop pgid=${EVAL_PGID} pid=${EVAL_PID} elapsed_s=${ELAPSED} eval_id=${EVAL_ID}" >>"$RUN_LOG"
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
  sleep 1
done
if (( EC == 0 )); then
  wait "$EVAL_PID" 2>/dev/null
  EC=$?
fi

if kill -0 "$EVAL_PID" 2>/dev/null; then
  EC=124
  if [[ -n "${EVAL_PGID:-}" ]]; then
    kill -KILL -- "-${EVAL_PGID}" 2>/dev/null || true
  fi
  kill -KILL "$EVAL_PID" 2>/dev/null || true
  wait "$EVAL_PID" 2>/dev/null || true
fi

END_EPOCH="$(date +%s)"
ELAPSED=$((END_EPOCH - START_EPOCH))
if (( EC == 124 )) && ! grep -q "slot_timeout=1 stall_guard.*eval_id=${EVAL_ID}" "$RUN_LOG" 2>/dev/null; then
  echo "slot_timeout=1 stall_guard wait_exit=124 elapsed_s=${ELAPSED} eval_id=${EVAL_ID}" >>"$RUN_LOG"
fi
if (( EC == 137 || EC == 143 )); then
  EC=124
fi
set -e
echo "$EC"
