#!/usr/bin/env bash
# R2 exam: 268 slots, enforceable 15m cap + stall guard, resume via START_IDX / RESUME=1.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
ART="$REPO_ROOT/exam-artifacts/r2"
BOT="$REPO_ROOT/review-gate-bot"
PLAN="$ART/run-plan.json"
BASE_SHA="532f3fbd"
FIX_SHA="d7345633"
TAG="${BASE_SHA}-${FIX_SHA}"
RUN_LOG="$ART/r2-run-${TAG}.log"
AUDIT="$ART/slot-audit-r2-${TAG}.ndjson"
AGG="$ART/runs/review-gate-r2-${TAG}.json"
SYNC="$ART/sync-bot-checkout.sh"
PREF="$ART/preflight-r2-slot.sh"
SLOT_RUN="$ART/run-r2-slot-capped.sh"
APPEND="$ART/append-slot-audit-line.mjs"
MERGE="$ART/merge-slot-into-wave-json.mjs"
STRIKE_FILE="$ART/.hang-strikes"
PROGRESS_FILE="$ART/.run-progress.json"
SLOT_WALL_SEC="${SLOT_WALL_SEC:-900}"
RESUME="${RESUME:-0}"
START_IDX="${START_IDX:-0}"

mkdir -p "$ART/runs"
if [[ "$RESUME" != "1" ]] && (( START_IDX == 0 )); then
  : >"$AUDIT"
  echo '{"results":[]}' >"$AGG"
  echo 0 >"$STRIKE_FILE"
else
  touch "$AUDIT"
  if [[ ! -f "$AGG" ]]; then
    echo '{"results":[]}' >"$AGG"
  fi
  if [[ ! -f "$STRIKE_FILE" ]]; then
    echo 0 >"$STRIKE_FILE"
  fi
  if [[ -f "$PROGRESS_FILE" ]] && [[ "$START_IDX" == "0" ]]; then
    START_IDX="$(python3 -c "import json; print(json.load(open('$PROGRESS_FILE')).get('lastCompletedIdx',-1)+1)")"
  fi
fi

exec >>"$RUN_LOG" 2>&1
HARNESS_TIP="$(git -C "$REPO_ROOT" rev-parse HEAD 2>/dev/null || echo unknown)"
echo "=== R2 $( [[ "$RESUME" == 1 ]] && echo resume || echo start ) $(date -u +%Y-%m-%dT%H:%M:%SZ) fixtures=${FIX_SHA} base_bot=${BASE_SHA} START_IDX=${START_IDX} slot_wall_s=${SLOT_WALL_SEC} harness=${HARNESS_TIP:0:8} ==="
if [[ "$RESUME" == "1" ]] && (( START_IDX == 162 )); then
  python3 - <<PY >>"$AUDIT"
import json, datetime
print(json.dumps({
  "auditNote": "launcher_resumed_at_162",
  "planIdx": 162,
  "priorHarnessSha": "7e76e69cbd6d46322f2d46272d9a54339a8a9da7",
  "harnessSha": "$HARNESS_TIP",
  "slotLauncher": "run-r2-slot-capped.sh",
  "at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
}))
PY
  echo "audit_note=launcher_resumed_at_162 harness=${HARNESS_TIP}"
fi
echo "fixture_pin_full=$(git -C "$REPO_ROOT" rev-parse HEAD)"
echo "plan_slots=$(python3 -c "import json; print(len(json.load(open('$PLAN'))['slots']))")"
echo "audit_lines_existing=$(wc -l <"$AUDIT" | tr -d ' ')"

TOTAL="$(python3 -c "import json; print(len(json.load(open('$PLAN'))['slots']))")"

python3 - <<PY > /tmp/r2-slot-lines.tsv
import json
plan = json.load(open("$PLAN"))
for i, s in enumerate(plan["slots"]):
    print("\t".join([
        str(i),
        s["evalId"],
        s["condition"],
        s["role"],
        s["botCheckoutSha"],
        s["r2MethodArm"],
        s["caseSlug"],
        str(s["iteration"]),
    ]))
PY

cd "$BOT"
npm ci --silent 2>/dev/null || npm install --silent

record_timeout() {
  local idx=$1 eval_id=$2 case_slug=$3 iter_num=$4 condition=$5 role=$6 bot_sha=$7 method_arm=$8
  local slot_start=$9 slot_end=${10}
  local sysprompt_chars=${11} sysprompt_sha=${12} model_json=${13} fix_full=${14}
  STRIKES=$(($(cat "$STRIKE_FILE") + 1))
  echo "$STRIKES" >"$STRIKE_FILE"
  echo "slot_timeout=1 eval_id=${eval_id} idx=${idx} at=${slot_end} strikes=${STRIKES}" 
  node "$APPEND" --audit "$AUDIT" --sysprompt-chars "$sysprompt_chars" --sysprompt-sha "$sysprompt_sha" \
    --model-json "$model_json" --fixture-pin "$fix_full" --eval-id "$eval_id" --case-id "$case_slug" \
    --iteration "$iter_num" --condition "$condition" --role "$role" --bot-checkout-sha "$bot_sha" \
    --r2-method-arm "$method_arm" --plan-idx "$idx" --slot-started-at "$slot_start" --slot-ended-at "$slot_end" --timed-out true
  python3 - <<PY
import json
json.dump({"lastCompletedIdx": int("$idx"), "slotTimeoutCount": int("$STRIKES"), "stopped": False}, open("$PROGRESS_FILE","w"))
PY
  if (( STRIKES >= 3 )); then
    echo "STOP third hang (permanent) eval_id=${eval_id} idx=${idx}"
    exit 12
  fi
}

while IFS=$'\t' read -r IDX EVAL_ID CONDITION ROLE BOT_SHA METHOD_ARM CASE_SLUG ITER_NUM; do
  if (( IDX < START_IDX )); then
    continue
  fi
  echo "PROGRESS slot=$((IDX + 1))/${TOTAL} idx=${IDX} eval_id=${EVAL_ID} condition=${CONDITION} bot=${BOT_SHA:0:8} arm=${METHOD_ARM}"
  bash "$SYNC" "$BOT_SHA"
  export R2_METHOD_ARM="$METHOD_ARM"
  PREF_OUT="$(bash "$PREF")" || {
    echo "STOP V1 preflight fail eval_id=${EVAL_ID}"
    echo "$PREF_OUT"
    exit 10
  }
  SYSPROMPT_CHARS="$(echo "$PREF_OUT" | sed -n 's/^sysprompt_chars=\([0-9]*\)$/\1/p' | head -1)"
  SYSPROMPT_SHA="$(echo "$PREF_OUT" | sed -n 's/^sysprompt_sha256=\([a-f0-9]\{64\}\)$/\1/p' | head -1)"
  MODEL_JSON="$(echo "$PREF_OUT" | sed -n 's/^model_object=\(.*\)/\1/p')"
  FIX_FULL="$(python3 -c "import json; print(json.load(open('$PLAN'))['fixturePinSha'])")"

  SLOT_START="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "SLOT_START idx=${IDX} eval_id=${EVAL_ID} at=${SLOT_START}"
  SLOT_JSON="$(mktemp /tmp/r2-slot-XXXX.json)"
  STATE="/tmp/r2-slot-state-${IDX}-$$-${RANDOM}"
  rm -rf "$STATE"

  provider_flake_retry() {
    [[ -s "$SLOT_JSON" ]] && grep -q 'trouble connecting to the model provider' "$SLOT_JSON"
  }

  EC="$(bash "$SLOT_RUN" "$BOT" "$EVAL_ID" "$STATE" "$SLOT_JSON" "$METHOD_ARM" "$SLOT_WALL_SEC" "$RUN_LOG")"
  RETRY_OF_IDX=""
  if [[ "$EC" -ne 0 ]] && [[ "$EC" -ne 124 ]] && provider_flake_retry; then
    FAIL_END="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    FAIL_JSON="$(mktemp /tmp/r2-slot-fail-XXXX.json)"
    cp "$SLOT_JSON" "$FAIL_JSON"
    echo "provider_flake_retry eval_id=${EVAL_ID} idx=${IDX} exit=${EC} sleep_s=45 record_slot_failed=1" >>"$RUN_LOG"
    node "$APPEND" --audit "$AUDIT" --sysprompt-chars "$SYSPROMPT_CHARS" --sysprompt-sha "$SYSPROMPT_SHA" \
      --model-json "$MODEL_JSON" --fixture-pin "$FIX_FULL" --eval-id "$EVAL_ID" --case-id "$CASE_SLUG" \
      --iteration "$ITER_NUM" --condition "$CONDITION" --role "$ROLE" --bot-checkout-sha "$BOT_SHA" \
      --r2-method-arm "$METHOD_ARM" --plan-idx "$IDX" --slot-started-at "$SLOT_START" --slot-ended-at "$FAIL_END" \
      --slot-failed true --slot-failed-reason "provider_error_exit_${EC}" --slot-json "$FAIL_JSON"
    rm -f "$FAIL_JSON"
    rm -f "$SLOT_JSON"
    rm -rf "$STATE"
    sleep 45
    RETRY_OF_IDX="$IDX"
    SLOT_START="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "SLOT_START idx=${IDX} eval_id=${EVAL_ID} retry_of_idx=${IDX} at=${SLOT_START}" >>"$RUN_LOG"
    STATE="/tmp/r2-slot-state-${IDX}-$$-${RANDOM}"
    SLOT_JSON="$(mktemp /tmp/r2-slot-XXXX.json)"
    EC="$(bash "$SLOT_RUN" "$BOT" "$EVAL_ID" "$STATE" "$SLOT_JSON" "$METHOD_ARM" "$SLOT_WALL_SEC" "$RUN_LOG")"
  fi
  SLOT_END="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  rm -rf "$STATE"

  if [[ "$EC" -eq 124 ]] || [[ "$EC" -eq 137 ]]; then
    record_timeout "$IDX" "$EVAL_ID" "$CASE_SLUG" "$ITER_NUM" "$CONDITION" "$ROLE" "$BOT_SHA" "$METHOD_ARM" \
      "$SLOT_START" "$SLOT_END" "$SYSPROMPT_CHARS" "$SYSPROMPT_SHA" "$MODEL_JSON" "$FIX_FULL"
    rm -f "$SLOT_JSON"
    echo "SLOT_END idx=${IDX} eval_id=${EVAL_ID} exit=timeout at=${SLOT_END}"
    continue
  fi
  if [[ "$EC" -ne 0 ]] || [[ ! -s "$SLOT_JSON" ]]; then
    FAIL_END="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    node "$APPEND" --audit "$AUDIT" --sysprompt-chars "$SYSPROMPT_CHARS" --sysprompt-sha "$SYSPROMPT_SHA" \
      --model-json "$MODEL_JSON" --fixture-pin "$FIX_FULL" --eval-id "$EVAL_ID" --case-id "$CASE_SLUG" \
      --iteration "$ITER_NUM" --condition "$CONDITION" --role "$ROLE" --bot-checkout-sha "$BOT_SHA" \
      --r2-method-arm "$METHOD_ARM" --plan-idx "$IDX" --slot-started-at "$SLOT_START" --slot-ended-at "$FAIL_END" \
      --slot-failed true --slot-failed-reason "eval_exit_${EC}" ${SLOT_JSON:+--slot-json "$SLOT_JSON"}
    echo "STOP slot_failed eval_id=${EVAL_ID} exit=${EC}"
    exit 11
  fi
  node "$MERGE" "$AGG" "$SLOT_JSON" "$EVAL_ID"
  EXTRA_RETRY=()
  if [[ -n "$RETRY_OF_IDX" ]]; then
    EXTRA_RETRY=(--retry-of-idx "$RETRY_OF_IDX" --attempt 2)
  elif [[ -f "$ART/.retry-next-plan-idx" ]] && [[ "$(cat "$ART/.retry-next-plan-idx")" == "$IDX" ]]; then
    EXTRA_RETRY=(--retry-of-idx "$IDX" --attempt 2)
    rm -f "$ART/.retry-next-plan-idx"
  fi
  node "$APPEND" --audit "$AUDIT" --sysprompt-chars "$SYSPROMPT_CHARS" --sysprompt-sha "$SYSPROMPT_SHA" \
    --model-json "$MODEL_JSON" --fixture-pin "$FIX_FULL" --eval-id "$EVAL_ID" --case-id "$CASE_SLUG" \
    --iteration "$ITER_NUM" --condition "$CONDITION" --role "$ROLE" --bot-checkout-sha "$BOT_SHA" \
    --r2-method-arm "$METHOD_ARM" --plan-idx "$IDX" --slot-started-at "$SLOT_START" --slot-ended-at "$SLOT_END" \
    --slot-json "$SLOT_JSON" "${EXTRA_RETRY[@]}"
  rm -f "$SLOT_JSON"
  echo "SLOT_END idx=${IDX} eval_id=${EVAL_ID} exit=${EC} at=${SLOT_END}"
  python3 - <<PY
import json
from pathlib import Path
p=Path("$PROGRESS_FILE")
doc=json.loads(p.read_text()) if p.is_file() else {}
doc.update({"lastCompletedIdx": $IDX, "slotTimeoutCount": int(Path("$STRIKE_FILE").read_text().strip() or 0), "stopped": False})
p.write_text(json.dumps(doc))
PY
done < /tmp/r2-slot-lines.tsv

TO="$(grep -c 'slot_timeout=1' "$RUN_LOG" 2>/dev/null || true)"
echo "=== R2 complete $(date -u +%Y-%m-%dT%H:%M:%SZ) audit_lines=$(wc -l <"$AUDIT" | tr -d ' ') slot_timeout_count=${TO} ==="
