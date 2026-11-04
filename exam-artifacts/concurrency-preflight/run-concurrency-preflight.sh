#!/usr/bin/env bash
# SD-105: two eval slots in parallel once — timings and API errors only (no scoring).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
BOT="$REPO_ROOT/review-gate-bot"
PLAN="$REPO_ROOT/exam-artifacts/concurrency-preflight/run-plan.json"
ART="$REPO_ROOT/exam-artifacts/concurrency-preflight"
PREF="$REPO_ROOT/exam-artifacts/r1-f3/preflight-r1-packb-a.sh"
LOG="$ART/concurrency-preflight-run.log"
SUMMARY="$ART/summary.json"
SLOT_WALL_SEC="$(python3 -c "import json; print(json.load(open('$PLAN'))['slotWallSec'])")"

mkdir -p "$ART/runs" "$ART/slots"
: >"$LOG"

exec > >(tee -a "$LOG") 2>&1
echo "=== concurrency-preflight start $(date -u +%Y-%m-%dT%H:%M:%SZ) parallel=2 no_scoring=true ==="
echo "git_rev=$(git -C "$REPO_ROOT" rev-parse HEAD)"
echo "plan=$(cat "$PLAN")"

cd "$BOT"
export R2_METHOD_ARM=A
PREF_OUT="$(bash "$PREF")"
echo "$PREF_OUT"
echo "$PREF_OUT" | grep -q preflight_ok || { echo "STOP preflight failed"; exit 3; }

HERMETIC=(env -i HOME="$HOME" PATH="$PATH" USER="${USER:-ubuntu}" TMPDIR="${TMPDIR:-/tmp}"
  CURSOR_API_KEY="${CURSOR_API_KEY:?CURSOR_API_KEY required}" R2_METHOD_ARM=A)

readarray -t EVAL_IDS < <(python3 -c "import json; print('\n'.join(json.load(open('$PLAN'))['evalIds']))")

PARALLEL_START="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
PARALLEL_START_EPOCH="$(date +%s)"
echo "PARALLEL_START at=${PARALLEL_START} eval_ids=${EVAL_IDS[*]}"

run_slot() {
  local idx="$1"
  local eval_id="$2"
  local slot_log="$ART/slots/slot-${idx}.log"
  local slot_json="$ART/runs/slot-${idx}.json"
  local state="/tmp/concurrency-preflight-state-${idx}-$$"
  rm -rf "$state"
  local t0 t1 ec
  t0="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "SLOT_${idx}_START eval_id=${eval_id} at=${t0}" | tee -a "$LOG" "$slot_log"
  set +e
  timeout --kill-after=30 "$SLOT_WALL_SEC" "${HERMETIC[@]}" bash -lc \
    "cd '$BOT' && npx agent-sdk eval --dir . $(printf '%q' "$eval_id") --json --no-stream --max-concurrency 1 --state-root '$state' --out '$slot_json'" \
    >>"$slot_log" 2>&1
  ec=$?
  set -e
  t1="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  rm -rf "$state"
  local status="failed"
  if [[ "$ec" -eq 124 ]] || [[ "$ec" -eq 137 ]]; then
    status="timeout"
  elif [[ "$ec" -eq 0 ]] && [[ -s "$slot_json" ]]; then
    status="completed"
  fi
  echo "SLOT_${idx}_END eval_id=${eval_id} at=${t1} exit=${ec} status=${status}" | tee -a "$LOG" "$slot_log"
  python3 - <<PY >"$ART/slots/slot-${idx}-meta.json"
import json, re, pathlib
slot_log = pathlib.Path("$slot_log").read_text(errors="replace")
rate_hits = []
for pat in (r"rate.?limit", r"429", r"too many requests", r"quota", r"RESOURCE_EXHAUSTED"):
    if re.search(pat, slot_log, re.I):
        rate_hits.append(pat)
json.dump({
  "slotIndex": $idx,
  "evalId": "$eval_id",
  "startedAt": "$t0",
  "endedAt": "$t1",
  "exitCode": $ec,
  "status": "$status",
  "outputJson": "$slot_json",
  "slotLog": "$slot_log",
  "rateLimitSignals": rate_hits,
}, open(1, "w"))
PY
}

pids=()
for i in "${!EVAL_IDS[@]}"; do
  run_slot "$i" "${EVAL_IDS[$i]}" &
  pids+=($!)
done
for p in "${pids[@]}"; do
  wait "$p" || true
done

PARALLEL_END="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
PARALLEL_END_EPOCH="$(date +%s)"
WALL=$((PARALLEL_END_EPOCH - PARALLEL_START_EPOCH))
echo "PARALLEL_END at=${PARALLEL_END} wall_seconds=${WALL}"

python3 - <<PY
import json, pathlib
art = pathlib.Path("$ART/slots")
lines = [json.loads(p.read_text()) for p in sorted(art.glob("slot-*-meta.json"))]
plan = json.load(open("$PLAN"))
out = {
  "runLabel": plan["runLabel"],
  "noScoring": True,
  "harnessSha": plan["harnessSha"],
  "fixturePinSha": plan["fixturePinSha"],
  "worktreeHarnessCommit": plan["worktreeHarnessCommit"],
  "parallelStart": "$PARALLEL_START",
  "parallelEnd": "$PARALLEL_END",
  "wallSeconds": $WALL,
  "slots": lines,
  "aggregate": {
    "completed": sum(1 for s in lines if s["status"] == "completed"),
    "timeout": sum(1 for s in lines if s["status"] == "timeout"),
    "failed": sum(1 for s in lines if s["status"] == "failed"),
    "anyRateLimitSignal": any(s.get("rateLimitSignals") for s in lines),
  },
}
pathlib.Path("$SUMMARY").write_text(json.dumps(out, indent=2) + "\n")
print(json.dumps(out["aggregate"]))
PY

echo "=== concurrency-preflight complete $(date -u +%Y-%m-%dT%H:%M:%SZ) summary=$SUMMARY ==="
