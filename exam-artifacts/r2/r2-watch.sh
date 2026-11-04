#!/usr/bin/env bash
# Watch R2 run: if no audit/log progress for 30m, alert on PR #1544.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
ART="$REPO_ROOT/exam-artifacts/r2"
AUDIT="$ART/slot-audit-r2-532f3fbd-d7345633.ndjson"
RUN_LOG="$ART/r2-run-532f3fbd-d7345633.log"
STATE="$ART/.watch-state.json"
STALL_SEC="${STALL_SEC:-1800}"
PR=1544

init_state() {
  if [[ ! -f "$STATE" ]]; then
    python3 - <<PY
import json, time
json.dump({"auditLines": 0, "lastProgressEpoch": int(time.time()), "alertedForStall": False}, open("$STATE","w"))
PY
  fi
}

init_state

while true; do
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
    state = {"auditLines": audit_lines, "lastProgressEpoch": now, "alertedForStall": False, "progress": prog}
    json.dump(state, open(state_path, "w"))
    print(f"r2-watch ok audit_lines={audit_lines} idx={prog.get('lastCompletedIdx')}")
else:
    stall_for = now - prev_ts
    if stall_for >= stall_sec and not alerted:
        msg = f"""## R2 stall alert (watchdog)

No progress for **{stall_for}s** (threshold {stall_sec}s).

- Audit lines: **{audit_lines}** / 268
- Progress: `{json.dumps(prog)}`
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
  sleep 300
done
