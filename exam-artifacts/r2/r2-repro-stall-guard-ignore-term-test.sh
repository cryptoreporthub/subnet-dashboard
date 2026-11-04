#!/usr/bin/env bash
# Repro: ignore-SIGTERM stub (parent+child) through run-r2-slot-capped.sh; Run A big / Run B fresh log.
set -euo pipefail
ART="$(cd "$(dirname "$0")" && pwd)"
CAPPED="$ART/run-r2-slot-capped.sh"
SRC_BIG="$ART/r2-run-532f3fbd-d7345633.log"
REPRO_DIR="$ART/repro-ignore-term-$(date +%Y%m%dT%H%M%SZ)"
mkdir -p "$REPRO_DIR"
MAX_OK=$((900 + 60))
MARKER="repro_ignore_term_$$"

check_survivors() {
  local marker="$1"
  pgrep -af "$marker" 2>/dev/null | grep -v 'pgrep -af' || true
}

run_one() {
  local label="$1"
  local log="$2"
  local state="/tmp/r2-repro-ign-${label}-$$"
  local out="/tmp/r2-repro-ign-out-${label}-$$.json"
  rm -rf "$state"
  local t0 t1 ec elapsed timeout_line guard_elapsed survivors pass
  t0="$(date +%s)"
  echo "=== repro_ignore_${label}_start $(date -u +%Y-%m-%dT%H:%M:%SZ) log_bytes=$(wc -c <"$log" | tr -d ' ') marker=${MARKER} ===" >>"$log"
  ec="$(R2_REPRO_STUB_EVAL=2 R2_STUB_MARKER="$MARKER" bash "$CAPPED" /tmp "$MARKER" "$state" "$out" A 900 "$log")"
  t1="$(date +%s)"
  elapsed=$((t1 - t0))
  timeout_line="$(grep 'slot_timeout=1 stall_guard' "$log" | tail -1 || true)"
  guard_elapsed="$(sed -n 's/.*elapsed_s=\([0-9]*\).*/\1/p' <<<"${timeout_line:-}" | tail -1)"
  [[ -n "$guard_elapsed" ]] || guard_elapsed="$elapsed"
  survivors="$(check_survivors "$MARKER")"
  pass=fail
  if [[ "$ec" == "124" ]] && [[ -n "$timeout_line" ]] && (( elapsed <= MAX_OK )) && (( guard_elapsed <= MAX_OK )) && [[ -z "$survivors" ]]; then
    pass=pass
  fi
  echo "--- repro_ignore_${label} ---"
  echo "exit=${ec} wall_elapsed_s=${elapsed} guard_elapsed_s=${guard_elapsed} max_ok=${MAX_OK} verdict=${pass}"
  echo "timeout_line=${timeout_line:-NONE}"
  echo "pgrep_survivors=${survivors:-NONE}"
  printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$label" "$ec" "$elapsed" "$guard_elapsed" "$pass" "${survivors:+HAS_SURVIVORS}"
}

LOG_A="$REPRO_DIR/run-a-big.log"
if [[ -f "$SRC_BIG" ]]; then cp "$SRC_BIG" "$LOG_A"; else head -c 13000000 /dev/zero | tr '\0' 'x' >"$LOG_A"; echo >>"$LOG_A"; fi
LOG_B="$REPRO_DIR/run-b-fresh.log"
: >"$LOG_B"

echo "=== R2 ignore-SIGTERM repro $(date -u +%Y-%m-%dT%H:%M:%SZ) SLOT_WALL_SEC=900 max_ok=${MAX_OK}s marker=${MARKER} ==="
echo "real_eval_path_in_run-r2-slot-capped.sh:"
sed -n '33,72p' "$CAPPED"
run_one A "$LOG_A"
run_one B "$LOG_B"
echo "artifacts_dir=${REPRO_DIR}"
