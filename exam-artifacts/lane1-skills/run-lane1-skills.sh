#!/usr/bin/env bash
# Lane 1 skills regression: 58 slots, 15m cap → NO_POST (new hang rule, no 3-strike stop).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
ART="$REPO_ROOT/exam-artifacts/lane1-skills"
R2="$REPO_ROOT/exam-artifacts/r2"
BOT="$REPO_ROOT/review-gate-bot"
PLAN="$ART/run-plan.json"
FIX_SHA="d7345633"
FRESH_SHA="532f3fbd"
CAND_SHA="6052d793"
TAG="${CAND_SHA}-${FIX_SHA}"
RUN_LOG="$ART/lane1-skills-run-${TAG}.log"
AUDIT="$ART/slot-audit-lane1-skills-${TAG}.ndjson"
AGG="$ART/runs/review-gate-lane1-skills-${TAG}.json"
SYNC="$R2/sync-bot-checkout.sh"
PREF="$ART/preflight-lane1-slot.sh"
SLOT_RUN="$R2/run-r2-slot-capped.sh"
APPEND="$R2/append-slot-audit-line.mjs"
MERGE="$R2/merge-slot-into-wave-json.mjs"
PROGRESS_FILE="$ART/.run-progress.json"
SLOT_WALL_SEC="${SLOT_WALL_SEC:-900}"
RESUME="${RESUME:-0}"
START_IDX="${START_IDX:-0}"

mkdir -p "$ART/runs"
python3 "$ART/generate-run-plan.py"
if [[ "$RESUME" != "1" ]] && (( START_IDX == 0 )); then
  : >"$AUDIT"
  echo '{"results":[]}' >"$AGG"
else
  touch "$AUDIT"
  [[ -f "$AGG" ]] || echo '{"results":[]}' >"$AGG"
  if [[ -f "$PROGRESS_FILE" ]] && [[ "$START_IDX" == "0" ]]; then
    START_IDX="$(python3 -c "import json; print(json.load(open('$PROGRESS_FILE')).get('lastCompletedIdx',-1)+1)")"
  fi
fi

exec >>"$RUN_LOG" 2>&1
HARNESS_TIP="$(git -C "$REPO_ROOT" rev-parse HEAD 2>/dev/null || echo unknown)"
echo "=== lane1-skills $( [[ "$RESUME" == 1 ]] && echo resume || echo start ) $(date -u +%Y-%m-%dT%H:%M:%SZ) fixtures=${FIX_SHA} freshA=${FRESH_SHA} candidate=${CAND_SHA} START_IDX=${START_IDX} slot_wall_s=${SLOT_WALL_SEC} harness=${HARNESS_TIP:0:8} ==="
echo "fixture_pin_full=$(python3 -c "import json; print(json.load(open('$PLAN'))['fixturePinSha'])")"
echo "plan_slots=$(python3 -c "import json; print(len(json.load(open('$PLAN'))['slots']))")"

TOTAL="$(python3 -c "import json; print(len(json.load(open('$PLAN'))['slots']))")"

python3 - <<PY > /tmp/lane1-slot-lines.tsv
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

while IFS=$'\t' read -r IDX EVAL_ID CONDITION ROLE BOT_SHA METHOD_ARM CASE_SLUG ITER_NUM; do
  if (( IDX < START_IDX )); then
    continue
  fi
  echo "PROGRESS slot=$((IDX + 1))/${TOTAL} idx=${IDX} eval_id=${EVAL_ID} condition=${CONDITION} role=${ROLE} bot=${BOT_SHA:0:8}"
  bash "$SYNC" "$BOT_SHA"
  export R2_METHOD_ARM="$METHOD_ARM"
  export LANE1_ROLE="$ROLE"
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
  SLOT_JSON="$(mktemp /tmp/lane1-slot-XXXX.json)"
  STATE="/tmp/lane1-slot-state-${IDX}-$$-${RANDOM}"
  rm -rf "$STATE"

  EC="$(bash "$SLOT_RUN" "$BOT" "$EVAL_ID" "$STATE" "$SLOT_JSON" "$METHOD_ARM" "$SLOT_WALL_SEC" "$RUN_LOG")"
  SLOT_END="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  rm -rf "$STATE"

  if [[ "$EC" -eq 124 ]] || [[ "$EC" -eq 137 ]]; then
    node "$APPEND" --audit "$AUDIT" --sysprompt-chars "$SYSPROMPT_CHARS" --sysprompt-sha "$SYSPROMPT_SHA" \
      --model-json "$MODEL_JSON" --fixture-pin "$FIX_FULL" --eval-id "$EVAL_ID" --case-id "$CASE_SLUG" \
      --iteration "$ITER_NUM" --condition "$CONDITION" --role "$ROLE" --bot-checkout-sha "$BOT_SHA" \
      --r2-method-arm "$METHOD_ARM" --plan-idx "$IDX" --slot-started-at "$SLOT_START" --slot-ended-at "$SLOT_END" --timed-out true
    rm -f "$SLOT_JSON"
    echo "SLOT_END idx=${IDX} eval_id=${EVAL_ID} exit=timeout capped_no_post at=${SLOT_END}"
    python3 - <<PY
import json
from pathlib import Path
p=Path("$PROGRESS_FILE")
doc=json.loads(p.read_text()) if p.is_file() else {}
doc.update({"lastCompletedIdx": $IDX, "stopped": False})
p.write_text(json.dumps(doc))
PY
    continue
  fi
  if [[ ! -s "$SLOT_JSON" ]]; then
    FAIL_END="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    node "$APPEND" --audit "$AUDIT" --sysprompt-chars "$SYSPROMPT_CHARS" --sysprompt-sha "$SYSPROMPT_SHA" \
      --model-json "$MODEL_JSON" --fixture-pin "$FIX_FULL" --eval-id "$EVAL_ID" --case-id "$CASE_SLUG" \
      --iteration "$ITER_NUM" --condition "$CONDITION" --role "$ROLE" --bot-checkout-sha "$BOT_SHA" \
      --r2-method-arm "$METHOD_ARM" --plan-idx "$IDX" --slot-started-at "$SLOT_START" --slot-ended-at "$FAIL_END" \
      --slot-failed true --slot-failed-reason "missing_slot_json_exit_${EC}"
    echo "STOP slot_failed eval_id=${EVAL_ID} exit=${EC} (no slot json)"
    exit 11
  fi
  node "$MERGE" "$AGG" "$SLOT_JSON" "$EVAL_ID"
  node "$APPEND" --audit "$AUDIT" --sysprompt-chars "$SYSPROMPT_CHARS" --sysprompt-sha "$SYSPROMPT_SHA" \
    --model-json "$MODEL_JSON" --fixture-pin "$FIX_FULL" --eval-id "$EVAL_ID" --case-id "$CASE_SLUG" \
    --iteration "$ITER_NUM" --condition "$CONDITION" --role "$ROLE" --bot-checkout-sha "$BOT_SHA" \
    --r2-method-arm "$METHOD_ARM" --plan-idx "$IDX" --slot-started-at "$SLOT_START" --slot-ended-at "$SLOT_END" \
    --slot-json "$SLOT_JSON"
  rm -f "$SLOT_JSON"
  echo "SLOT_END idx=${IDX} eval_id=${EVAL_ID} exit=${EC} at=${SLOT_END}"
  if [[ "$EC" -ne 0 ]]; then
    echo "NOTE: agent-sdk exit ${EC} (raw JSON published; Claude scores)"
  fi
  python3 - <<PY
import json
from pathlib import Path
p=Path("$PROGRESS_FILE")
doc=json.loads(p.read_text()) if p.is_file() else {}
doc.update({"lastCompletedIdx": $IDX, "stopped": False})
p.write_text(json.dumps(doc))
PY
done < /tmp/lane1-slot-lines.tsv

TO="$(grep -c 'exit=timeout capped_no_post' "$RUN_LOG" 2>/dev/null || true)"
echo "=== lane1-skills complete $(date -u +%Y-%m-%dT%H:%M:%SZ) audit_lines=$(wc -l <"$AUDIT" | tr -d ' ') capped_no_post=${TO} harness=${HARNESS_TIP} ==="
