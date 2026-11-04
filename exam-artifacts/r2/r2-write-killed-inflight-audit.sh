#!/usr/bin/env bash
# Append killed in-flight attempt audit line (watchdog) before RESUME restart.
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
ART="$REPO_ROOT/exam-artifacts/r2"
PLAN="$ART/run-plan.json"
AUDIT="$ART/slot-audit-r2-532f3fbd-d7345633.ndjson"
APPEND="$ART/append-slot-audit-line.mjs"
SYNC="$ART/sync-bot-checkout.sh"
PREF="$ART/preflight-r2-slot.sh"
BOT="$REPO_ROOT/review-gate-bot"
RUN_LOG="${1:-$ART/r2-run-532f3fbd-d7345633.log}"

eval "$(python3 "$ART/r2-watch-detect-inflight.py" "$RUN_LOG")"
PLAN_IDX="${inflight_idx:-}"
SLOT_START="${inflight_started_at:-}"
[[ -n "$PLAN_IDX" && -n "$SLOT_START" ]] || {
  echo "r2-write-killed skip no_inflight" >>"$RUN_LOG"
  exit 0
}

KILL_END="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
python3 - <<PY >>"$RUN_LOG"
import json
from pathlib import Path
audit = Path("$AUDIT")
plan_idx = int("$PLAN_IDX")
slot_start = "$SLOT_START"
if audit.is_file():
    for line in audit.read_text().splitlines():
        if not line.strip():
            continue
        o = json.loads(line)
        if o.get("planIdx") == plan_idx and o.get("slotStartedAt") == slot_start and o.get("slotKilled"):
            print(f"r2-write-killed skip duplicate planIdx={plan_idx} start={slot_start}")
            raise SystemExit(0)
PY

read -r EVAL_ID CONDITION ROLE BOT_SHA METHOD_ARM CASE_SLUG ITER_NUM < <(
  python3 - <<PY
import json
s = json.load(open("$PLAN"))["slots"][int("$PLAN_IDX")]
print(
    s["evalId"],
    s["condition"],
    s["role"],
    s["botCheckoutSha"],
    s["r2MethodArm"],
    s["caseSlug"],
    str(s["iteration"]),
    sep="\t",
)
PY
)

ATTEMPT="$(python3 - <<PY
import json
from pathlib import Path
plan_idx = int("$PLAN_IDX")
eval_id = """$EVAL_ID"""
slot_start = """$SLOT_START"""
n = 0
p = Path("$AUDIT")
if p.is_file():
    for line in p.read_text().splitlines():
        if not line.strip():
            continue
        o = json.loads(line)
        if o.get("planIdx") == plan_idx and o.get("evalId") == eval_id:
            n += 1
print(max(1, n + 1))
PY
)"

bash "$SYNC" "$BOT_SHA" >/dev/null
cd "$BOT"
export R2_METHOD_ARM="$METHOD_ARM"
PREF_OUT="$(bash "$PREF")" || exit 2
SYSPROMPT_CHARS="$(echo "$PREF_OUT" | sed -n 's/^sysprompt_chars=\([0-9]*\)$/\1/p' | head -1)"
SYSPROMPT_SHA="$(echo "$PREF_OUT" | sed -n 's/^sysprompt_sha256=\([a-f0-9]\{64\}\)$/\1/p' | head -1)"
MODEL_JSON="$(echo "$PREF_OUT" | sed -n 's/^model_object=\(.*\)/\1/p')"
FIX_FULL="$(python3 -c "import json; print(json.load(open('$PLAN'))['fixturePinSha'])")"

node "$APPEND" --audit "$AUDIT" --sysprompt-chars "$SYSPROMPT_CHARS" --sysprompt-sha "$SYSPROMPT_SHA" \
  --model-json "$MODEL_JSON" --fixture-pin "$FIX_FULL" --eval-id "$EVAL_ID" --case-id "$CASE_SLUG" \
  --iteration "$ITER_NUM" --condition "$CONDITION" --role "$ROLE" --bot-checkout-sha "$BOT_SHA" \
  --r2-method-arm "$METHOD_ARM" --plan-idx "$PLAN_IDX" --attempt "$ATTEMPT" \
  --slot-started-at "$SLOT_START" --slot-ended-at "$KILL_END" \
  --slot-killed true --kill-reason "watchdog_restart_runner_dead_inflight"

echo "$PLAN_IDX" >"$ART/.retry-next-plan-idx"
echo "r2-write-killed ok planIdx=${PLAN_IDX} attempt=${ATTEMPT} start=${SLOT_START} end=${KILL_END}" >>"$RUN_LOG"
