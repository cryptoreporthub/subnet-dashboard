#!/usr/bin/env bash
# Stage 2 soak probe: prove web→worker private HTTP over a sustained window.
#
# Run FROM GHA (preferred) or any always-on host with flyctl. Each tick does
# fly machine exec on the web machine → probe_worker_peer_once.py.
#
# Requirements:
#   - 4h minimum (SOAK_HOURS), every 5 min (PROBE_INTERVAL_SECONDS)
#   - ZERO failures across the entire window (one miss = restart the clock)
#   - Fail if probe cadence gap exceeds interval + margin (VM suspend guard)
#   - Every probe result logged with timestamp + machine state
#   - Exit nonzero on any failure (including lease conflicts)
#
# This log doubles as Stage 4 soak evidence — don't discard it.
#
# Safety: refuses to run if fly_enable_worker_v2.sh still has the old
# secret-before-deploy ordering (see FIRST ENGINEERING PR requirement).
set -euo pipefail

APP="${FLY_APP:-subnet-dashboard}"
SOAK_HOURS="${SOAK_HOURS:-4}"
PROBE_INTERVAL_SECONDS="${PROBE_INTERVAL_SECONDS:-300}"
# ponytail: 60s margin catches tmux/VM suspend gaps; tune via SOAK_GAP_MARGIN_SECONDS.
GAP_MARGIN_SECONDS="${SOAK_GAP_MARGIN_SECONDS:-60}"
MAX_GAP_SECONDS=$((PROBE_INTERVAL_SECONDS + GAP_MARGIN_SECONDS))
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOGFILE="${SOAK_LOG:-/tmp/fly_soak_probe_$(date +%Y%m%d_%H%M%S).log}"

total_probes=$(( (SOAK_HOURS * 3600) / PROBE_INTERVAL_SECONDS ))

echo "== Stage 2 soak probe: $APP ==" | tee "$LOGFILE"
echo "Duration: ${SOAK_HOURS}h, interval: ${PROBE_INTERVAL_SECONDS}s, probes: $total_probes" | tee -a "$LOGFILE"
echo "Max allowed gap: ${MAX_GAP_SECONDS}s (interval + ${GAP_MARGIN_SECONDS}s margin)" | tee -a "$LOGFILE"
echo "Log: $LOGFILE" | tee -a "$LOGFILE"
echo "" | tee -a "$LOGFILE"

# --- Safety check: enable script must have correct ordering ---
if [ -f "$SCRIPT_DIR/fly_enable_worker_v2.sh" ]; then
  if grep -qE '=== 2\.' "$SCRIPT_DIR/fly_enable_worker_v2.sh" && \
     grep -A3 '=== 2\.' "$SCRIPT_DIR/fly_enable_worker_v2.sh" | grep -q 'flyctl secrets set WORKER_SPLIT_V2'; then
    echo "ABORT: fly_enable_worker_v2.sh still has secret-before-deploy ordering." | tee -a "$LOGFILE"
    echo "The enable script must set WORKER_SPLIT_V2=on AFTER worker is proven" | tee -a "$LOGFILE"
    echo "healthy on :8081. Fix the script first." | tee -a "$LOGFILE"
    exit 1
  fi
fi

if ! flyctl auth whoami 2>/dev/null; then
  echo "ABORT: flyctl not authenticated" | tee -a "$LOGFILE"
  exit 1
fi

chmod +x "$SCRIPT_DIR/fly_probe_worker_from_web.sh"

log_machine_state() {
  local web_id="${1:-}"
  flyctl machines list -a "$APP" --json 2>/dev/null | python3 -c "
import json, sys
web_id = sys.argv[1] if len(sys.argv) > 1 else ''
rows = json.load(sys.stdin)
for m in rows:
    mid = m.get('id', '')
    pg = ((m.get('config') or {}).get('metadata') or {}).get('fly_process_group', '?')
    state = m.get('state', '?')
    updated = m.get('updated_at', '?')
    tag = ' (web)' if mid == web_id else ''
    print(f'  machine {mid} pg={pg} state={state} updated={updated}{tag}')
    for ev in (m.get('events') or [])[:2]:
        print(f'    last_event: {ev.get(\"type\")} source={ev.get(\"source\")} ts={ev.get(\"timestamp\")}')
" "$web_id" 2>/dev/null || echo "  (machine state unavailable)"
}

WEB_ID="$(flyctl machines list -a "$APP" --json | python3 -c "
import json, sys
for m in json.load(sys.stdin):
    meta = (m.get('config') or {}).get('metadata') or {}
    pg = (meta.get('fly_process_group') or 'web').lower()
    if pg == 'web' and m.get('id'):
        print(m['id'])
        break
" 2>/dev/null || true)"

failures=0
successes=0
last_probe_epoch=0

for i in $(seq 1 "$total_probes"); do
  now_epoch="$(date +%s)"
  if [ "$last_probe_epoch" -gt 0 ]; then
    gap=$((now_epoch - last_probe_epoch))
    if [ "$gap" -gt "$MAX_GAP_SECONDS" ]; then
      failures=$((failures + 1))
      ts="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
      echo "[$ts] probe $i/$total_probes ... CADENCE GAP ${gap}s > max ${MAX_GAP_SECONDS}s" | tee -a "$LOGFILE"
      echo "SOAK FAILED: probe cadence gap (${gap}s) exceeds allowed ${MAX_GAP_SECONDS}s." | tee -a "$LOGFILE"
      echo "Runner infra suspended or sleep was interrupted — restart on GHA workflow_dispatch." | tee -a "$LOGFILE"
      exit 1
    fi
  fi
  last_probe_epoch="$now_epoch"

  ts="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
  echo "[$ts] probe $i/$total_probes ... " | tee -a "$LOGFILE"
  echo "[$ts] machine state:" | tee -a "$LOGFILE"
  log_machine_state "$WEB_ID" | tee -a "$LOGFILE"

  if [ "${SOAK_INSTRUMENT:-1}" != "0" ] && [ -x "$SCRIPT_DIR/fly_stage2_soak_sample.sh" ]; then
    SOAK_PROBE_N="$i" SOAK_SAMPLES_LOG="${SOAK_SAMPLES_LOG:-soak_samples.jsonl}" \
      FLY_APP="$APP" "$SCRIPT_DIR/fly_stage2_soak_sample.sh" 2>&1 | tee -a "$LOGFILE" || true
  fi

  probe_out="$(mktemp)"
  set +e
  FLY_APP="$APP" "$SCRIPT_DIR/fly_probe_worker_from_web.sh" > "$probe_out" 2>&1
  probe_rc=$?
  set -e
  cat "$probe_out" | tee -a "$LOGFILE"

  if grep -qi 'lease currently held' "$probe_out"; then
    rm -f "$probe_out"
    failures=$((failures + 1))
    echo "FAIL (lease conflict — concurrent flyctl holds machine lock)" | tee -a "$LOGFILE"
    echo "" | tee -a "$LOGFILE"
    echo "SOAK FAILED at probe $i: flyctl machine lease conflict." | tee -a "$LOGFILE"
    echo "Do not run prod flyctl ops during soak. Restart the clock." | tee -a "$LOGFILE"
    exit 1
  fi
  rm -f "$probe_out"

  if [ "$probe_rc" -eq 0 ]; then
    echo "OK" | tee -a "$LOGFILE"
    successes=$((successes + 1))
  else
    failures=$((failures + 1))
    echo "FAIL (total failures: $failures)" | tee -a "$LOGFILE"
    echo "" | tee -a "$LOGFILE"
    echo "SOAK FAILED at probe $i after $successes consecutive successes." | tee -a "$LOGFILE"
    echo "Zero-failure bar not met. Fix networking, then restart the clock." | tee -a "$LOGFILE"
    echo "" | tee -a "$LOGFILE"
    echo "Summary: $successes OK, $failures FAIL out of $i attempted" | tee -a "$LOGFILE"
    exit 1
  fi

  if [ "$i" -lt "$total_probes" ]; then
    sleep "$PROBE_INTERVAL_SECONDS"
  fi
done

echo "" | tee -a "$LOGFILE"
echo "== SOAK PASSED ==" | tee -a "$LOGFILE"
echo "All $successes probes succeeded over ${SOAK_HOURS}h with zero failures." | tee -a "$LOGFILE"
echo "Completed: $(date -u '+%Y-%m-%dT%H:%M:%SZ')" | tee -a "$LOGFILE"
echo "" | tee -a "$LOGFILE"
echo "This log is evidence for Stage 4 (24h post-cutover soak)." | tee -a "$LOGFILE"
echo "Do NOT discard it." | tee -a "$LOGFILE"
