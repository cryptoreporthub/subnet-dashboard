#!/usr/bin/env bash
# Watch R2: 30m stall PR alert; restart dead r2-run if in-flight slot >5m without SLOT_END.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
ART="$REPO_ROOT/exam-artifacts/r2"
AUDIT="$ART/slot-audit-r2-532f3fbd-d7345633.ndjson"
RUN_LOG="$ART/r2-run-532f3fbd-d7345633.log"
STATE="$ART/.watch-state.json"
STALL_SEC="${STALL_SEC:-1800}"
DEAD_INFLIGHT_SEC="${DEAD_INFLIGHT_SEC:-300}"
PR=1544
TMUX=(tmux -f /exec-daemon/tmux.portal.conf)
DETECT="$ART/r2-watch-detect-inflight.py"
RESTART="$ART/r2-restart-run.sh"

init_state() {
  if [[ ! -f "$STATE" ]]; then
    python3 - <<PY
import json, time
json.dump({"auditLines": 0, "lastProgressEpoch": int(time.time()), "alertedForStall": False}, open("$STATE","w"))
PY
  fi
}

r2_run_alive() {
  "${TMUX[@]}" has-session -t r2-run 2>/dev/null && pgrep -f '[/]exam-artifacts/r2/run-r2.sh' >/dev/null
}

log_runner_liveness() {
  if r2_run_alive; then
    echo "r2-watch liveness tmux=r2-run ok runner=run-r2.sh ok at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  else
    echo "r2-watch liveness tmux=r2-run DEAD or runner missing at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  fi
}

maybe_restart_dead_runner() {
  if [[ -f "$ART/.r2-gate-hold" ]]; then
    return 0
  fi
  if grep -q '^=== R2 complete ' "$RUN_LOG" 2>/dev/null; then
    return 0
  fi
  eval "$(python3 "$DETECT" "$RUN_LOG")"
  [[ -n "${inflight_idx:-}" ]] || return 0
  (( inflight_sec >= DEAD_INFLIGHT_SEC )) || return 0
  if r2_run_alive; then
    return 0
  fi
  LAST_RESTART="$(python3 -c "import json; print(json.load(open('$STATE')).get('lastAutoRestartEpoch',0))" 2>/dev/null || echo 0)"
  NOW_EPOCH="$(date +%s)"
  if (( NOW_EPOCH - LAST_RESTART < DEAD_INFLIGHT_SEC )); then
    echo "r2-watch skip_restart debounce idx=${inflight_idx}"
    return 0
  fi
  echo "r2-watch RESTART dead_runner idx=${inflight_idx} inflight_sec=${inflight_sec} threshold=${DEAD_INFLIGHT_SEC}"
  if ! bash "$RESTART" "$inflight_idx" >>"$RUN_LOG" 2>&1; then
    echo "r2-watch RESTART_ABORT idx=${inflight_idx} (harness gate or restart failed)" >>"$RUN_LOG"
    return 0
  fi
  python3 - <<PY
import json, time
s=json.load(open("$STATE")) if __import__("os").path.isfile("$STATE") else {}
s["lastAutoRestartEpoch"]=int(time.time())
s["lastAutoRestartIdx"]=int("$inflight_idx")
json.dump(s, open("$STATE","w"))
PY
  gh pr comment "$PR" --body "## R2 watchdog auto-restart (no scoring)

**Reason:** tmux \`r2-run\` / runner **not alive**; plan idx=**${inflight_idx}** in-flight **${inflight_sec}s** since \`${inflight_started_at:-SLOT_START}\` without \`SLOT_END\` (threshold **${DEAD_INFLIGHT_SEC}s**).

**Action:** \`RESUME=1 START_IDX=${inflight_idx}\` (no rerun of completed indices)." 2>/dev/null || true
}

init_state

TICK=0
while true; do
  maybe_restart_dead_runner
  if (( TICK % 5 == 0 )); then
    log_runner_liveness
  fi
  TICK=$((TICK + 1))
  NOW_EPOCH="$(date +%s)"
  LINES="$(wc -l <"$AUDIT" 2>/dev/null | tr -d ' ' || echo 0)"
  LOG_MTIME="$(stat -c %Y "$RUN_LOG" 2>/dev/null || echo 0)"
  PROG="$(cat "$ART/.run-progress.json" 2>/dev/null || echo '{}')"
  python3 - <<PY
import json, os, subprocess, time
state_path = "$STATE"
audit_lines = int("$LINES")
log_mtime = int("$LOG_MTIME")
now = int("$NOW_EPOCH")
stall_sec = int("$STALL_SEC")
prog = json.loads("""$PROG""".replace("\\\\", "\\\\\\\\") if """$PROG""" else {})
state = json.load(open(state_path)) if os.path.isfile(state_path) else {}
prev_lines = state.get("auditLines", -1)
prev_ts = state.get("lastProgressEpoch", now)
alerted = state.get("alertedForStall", False)
progress = audit_lines != prev_lines or log_mtime > prev_ts
if progress:
    state = {**state, "auditLines": audit_lines, "lastProgressEpoch": now, "alertedForStall": False, "progress": prog}
    json.dump(state, open(state_path, "w"))
    print(f"r2-watch ok audit_lines={audit_lines} idx={prog.get('lastCompletedIdx')}")
else:
    stall_for = now - prev_ts
    if stall_for >= stall_sec and not alerted:
        msg = f"""## R2 stall alert (watchdog)

No progress for **{stall_for}s** (threshold {stall_sec}s).

- Audit lines: **{audit_lines}** / 268
- Progress: \`{json.dumps(prog)}\`
- Log mtime epoch: {log_mtime}

Check tmux \`r2-run\`. Slot cap is 15m wall with process-group kill; this alert is **30m** without audit/log movement."""
        subprocess.run(["gh", "pr", "comment", "$PR", "--body", msg], check=False)
        state["alertedForStall"] = True
        json.dump(state, open(state_path, "w"))
        print(f"r2-watch STALL_ALERT stall_for={stall_for}s lines={audit_lines}")
    else:
        print(f"r2-watch idle stall_for={stall_for}s lines={audit_lines}")
PY
  if (( NOW_EPOCH % 1800 < 300 )); then
    bash "$REPO_ROOT/exam-artifacts/r2/r2-checkpoint-push.sh" >>"$ART/r2-checkpoint-push.log" 2>&1 || true
  fi
  sleep 60
done
