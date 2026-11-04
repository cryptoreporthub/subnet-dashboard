#!/usr/bin/env bash
# Item 2 repro: stub eval + shared RUN_LOG; Run A (~13MB log) vs Run B (fresh).
set -euo pipefail
ART="$(cd "$(dirname "$0")" && pwd)"
CAPPED="$ART/run-r2-slot-capped.sh"
SRC_BIG="$ART/r2-run-532f3fbd-d7345633.log"
REPRO_DIR="$ART/repro-stall-guard-$(date +%Y%m%dT%H%M%SZ)"
mkdir -p "$REPRO_DIR"
MAX_OK=$((900 + 60))

run_one() {
  local label="$1"
  local log="$2"
  local state="/tmp/r2-repro-state-${label}-$$"
  local out="/tmp/r2-repro-out-${label}-$$.json"
  rm -rf "$state"
  local t0 t1 ec elapsed timeout_line guard_elapsed pass
  t0="$(date +%s)"
  echo "=== repro_${label}_start $(date -u +%Y-%m-%dT%H:%M:%SZ) log_bytes=$(wc -c <"$log" | tr -d ' ') ===" >>"$log"
  ec="$(R2_REPRO_STUB_EVAL=1 bash "$CAPPED" /tmp repro-stall-guard "$state" "$out" A 900 "$log")"
  t1="$(date +%s)"
  elapsed=$((t1 - t0))
  timeout_line="$(grep 'slot_timeout=1 stall_guard' "$log" | tail -1 || true)"
  guard_elapsed="$(sed -n 's/.*elapsed_s=\([0-9]*\).*/\1/p' <<<"${timeout_line:-}" | tail -1)"
  [[ -n "$guard_elapsed" ]] || guard_elapsed="$elapsed"
  pass=fail
  if [[ "$ec" == "124" ]] && [[ -n "$timeout_line" ]] && (( elapsed <= MAX_OK )) && (( guard_elapsed <= MAX_OK )); then
    pass=pass
  fi
  echo "repro_${label} exit=${ec} wall_elapsed_s=${elapsed} guard_elapsed_s=${guard_elapsed} max_ok=${MAX_OK} verdict=${pass} log_bytes=$(wc -c <"$log" | tr -d ' ')"
  echo "repro_${label} timeout_line=${timeout_line:-NONE}"
  printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$label" "$ec" "$elapsed" "$guard_elapsed" "$pass" "$(wc -c <"$log" | tr -d ' ')"
}

LOG_A="$REPRO_DIR/run-a-big.log"
if [[ -f "$SRC_BIG" ]]; then
  cp "$SRC_BIG" "$LOG_A"
else
  head -c 13000000 /dev/zero | tr '\0' 'x' >"$LOG_A"
  echo >>"$LOG_A"
fi

LOG_B="$REPRO_DIR/run-b-fresh.log"
: >"$LOG_B"

echo "=== R2 stall-guard repro $(date -u +%Y-%m-%dT%H:%M:%SZ) SLOT_WALL_SEC=900 max_ok=${MAX_OK}s ==="
echo -e "run\texit\twall_s\tguard_elapsed_s\tverdict\tfinal_log_bytes"
run_one A "$LOG_A"
run_one B "$LOG_B"
echo "artifacts_dir=${REPRO_DIR}"
