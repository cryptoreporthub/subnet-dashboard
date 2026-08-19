#!/usr/bin/env bash
# Stage 2 soak probe: prove web→worker private HTTP over a sustained window.
#
# Run FROM the GHA runner (or any machine with flyctl). Each tick does
# fly machine exec on the web machine → probe_worker_peer_once.py.
#
# Requirements:
#   - 4h minimum (SOAK_HOURS), every 5 min (PROBE_INTERVAL_SECONDS)
#   - ZERO failures across the entire window (one miss = restart the clock)
#   - Every probe result logged with timestamp
#   - Exit nonzero on any failure
#
# This log doubles as Stage 4 soak evidence — don't discard it.
#
# Safety: refuses to run if fly_enable_worker_v2.sh still has the old
# secret-before-deploy ordering (see FIRST ENGINEERING PR requirement).
set -euo pipefail

APP="${FLY_APP:-subnet-dashboard}"
SOAK_HOURS="${SOAK_HOURS:-4}"
PROBE_INTERVAL_SECONDS="${PROBE_INTERVAL_SECONDS:-300}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOGFILE="${SOAK_LOG:-/tmp/fly_soak_probe_$(date +%Y%m%d_%H%M%S).log}"

total_probes=$(( (SOAK_HOURS * 3600) / PROBE_INTERVAL_SECONDS ))

echo "== Stage 2 soak probe: $APP ==" | tee "$LOGFILE"
echo "Duration: ${SOAK_HOURS}h, interval: ${PROBE_INTERVAL_SECONDS}s, probes: $total_probes" | tee -a "$LOGFILE"
echo "Log: $LOGFILE" | tee -a "$LOGFILE"
echo "" | tee -a "$LOGFILE"

# --- Safety check: enable script must have correct ordering ---
if [ -f "$SCRIPT_DIR/fly_enable_worker_v2.sh" ]; then
  # The old broken ordering had "Set WORKER_SPLIT_V2=on" as step 2 (before deploy).
  # The fixed ordering has it as step 6 (after worker proven healthy).
  # Detect the old pattern: "=== 2." line followed by "flyctl secrets set WORKER_SPLIT_V2".
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

failures=0
successes=0

for i in $(seq 1 "$total_probes"); do
  ts="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
  echo -n "[$ts] probe $i/$total_probes ... " | tee -a "$LOGFILE"

  if FLY_APP="$APP" "$SCRIPT_DIR/fly_probe_worker_from_web.sh" >> "$LOGFILE" 2>&1; then
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
