#!/usr/bin/env bash
# Resume R1-A2 after WAVE_1: backfill slot-audit from iter1 JSON, then run waves 2–3 only.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
BOT="$REPO_ROOT/review-gate-bot"
PLAN="$REPO_ROOT/exam-artifacts/r1-packb-a/run-plan.json"
EXTRACT="$REPO_ROOT/exam-artifacts/r1-packb-a/extract-slot-audit.mjs"
BACKFILL="$REPO_ROOT/exam-artifacts/r1-packb-a/backfill-wave1-slot-audit.mjs"
PARSE_W1="$REPO_ROOT/exam-artifacts/r1-packb-a/parse-wave1-preflight-from-log.sh"
SHA_SHORT="5d884c47"
FIX_SHA_FULL="$(python3 -c "import json; print(json.load(open('$PLAN'))['fixturePinSha'])")"
FIX_SHA="${FIX_SHA_FULL:0:8}"
RUN_LOG="$REPO_ROOT/exam-artifacts/r1-packb-a/r1-packb-a2-run-${SHA_SHORT}.log"
AUDIT="$REPO_ROOT/exam-artifacts/r1-packb-a/slot-audit-a2-${SHA_SHORT}.ndjson"
ITER1="$REPO_ROOT/exam-artifacts/r1-packb-a/runs/review-gate-r1packb-iter1-${SHA_SHORT}.json"

if [[ ! -f "$BACKFILL" ]] || [[ ! -f "$EXTRACT" ]]; then
  echo "STOP: missing audit scripts under exam-artifacts/r1-packb-a/"
  exit 2
fi
if [[ ! -f "$ITER1" ]]; then
  echo "STOP: missing wave-1 output $ITER1"
  exit 2
fi

exec >> >(tee -a "$RUN_LOG") 2>&1
echo "=== R1-A2 resume waves 2–3 $(date -u +%Y-%m-%dT%H:%M:%SZ) harness=$SHA_SHORT fixtures=$FIX_SHA ==="
echo "git_rev=$(git -C "$REPO_ROOT" rev-parse HEAD)"
echo "resume_path=backfill_wave1_audit_then_waves_2_3"

cd "$BOT"
export R2_METHOD_ARM=A

W1_PREF="$(bash "$PARSE_W1" "$RUN_LOG")" || { echo "STOP: wave-1 preflight not found in log"; exit 9; }
echo "wave1_preflight_from_log:"
echo "$W1_PREF"
W1_SYSPROMPT_CHARS="$(echo "$W1_PREF" | sed -n 's/^sysprompt_chars=\([0-9]*\)$/\1/p' | head -1)"
W1_SYSPROMPT_SHA="$(echo "$W1_PREF" | sed -n 's/^sysprompt_sha256=\([a-f0-9]\{64\}\)$/\1/p' | head -1)"
W1_MODEL_JSON="$(echo "$W1_PREF" | sed -n 's/^model_object=\(.*\)/\1/p')"
if [[ ${#W1_SYSPROMPT_SHA} -ne 64 ]]; then
  echo "STOP: wave-1 log sysprompt sha invalid (V1 fallback may apply)"
  exit 9
fi
EXPECTED_SHA="$(python3 -c "import json; print(json.load(open('$PLAN'))['expectedSyspromptSha256'])")"
EXPECTED_CHARS="$(python3 -c "import json; print(json.load(open('$PLAN'))['expectedSyspromptChars'])")"
if [[ "$W1_SYSPROMPT_SHA" != "$EXPECTED_SHA" || "$W1_SYSPROMPT_CHARS" != "$EXPECTED_CHARS" ]]; then
  echo "STOP: wave-1 V1 preflight mismatch vs run-plan (Claude 96-slot fallback)"
  exit 9
fi

PREF="$(bash "$REPO_ROOT/exam-artifacts/r1-packb-a/preflight-r1-packb-a.sh")"
echo "$PREF"
echo "$PREF" | grep -q preflight_ok || { echo "STOP preflight failed"; exit 3; }

SYSPROMPT_CHARS="$(echo "$PREF" | sed -n 's/^sysprompt_chars=\([0-9]*\)$/\1/p' | head -1)"
SYSPROMPT_SHA="$(echo "$PREF" | sed -n 's/^sysprompt_sha256=\([a-f0-9]\{64\}\)$/\1/p' | head -1)"
MODEL_JSON="$(echo "$PREF" | sed -n 's/^model_object=\(.*\)/\1/p')"
if [[ ${#SYSPROMPT_SHA} -ne 64 ]]; then
  echo "STOP: empty sysprompt sha256 (V1)"
  exit 5
fi

W1_COUNT="$(python3 -c "import json; print(len(json.load(open('$ITER1')).get('results',[])))")"
if [[ "$W1_COUNT" -ne 48 ]]; then
  echo "STOP: iter1 result count $W1_COUNT (expected 48)"
  exit 6
fi

AUDIT_LINES="$(wc -l <"$AUDIT" | tr -d ' ')"
NEEDS_BACKFILL=1
if [[ "$AUDIT_LINES" -ge 48 ]]; then
  if head -1 "$AUDIT" | python3 -c "import json,sys; d=json.load(sys.stdin); sys.exit(0 if d.get('backfilled') is True else 1)"; then
    NEEDS_BACKFILL=0
  fi
fi
if [[ "$NEEDS_BACKFILL" -eq 1 ]]; then
  if [[ "$AUDIT_LINES" -gt 48 ]]; then
    echo "STOP: audit has $AUDIT_LINES lines without compliant wave-1 backfill"
    exit 7
  fi
  echo "WAVE_1_AUDIT_BACKFILL $(date -u +%Y-%m-%dT%H:%M:%SZ) from=$ITER1 v1=wave1_log_preflight"
  node "$BACKFILL" "$ITER1" "$AUDIT" "$W1_SYSPROMPT_CHARS" "$W1_SYSPROMPT_SHA" "$W1_MODEL_JSON" "$FIX_SHA_FULL" "true"
  echo "WAVE_1_AUDIT_BACKFILL_DONE lines=$(wc -l <"$AUDIT" | tr -d ' ')"
elif [[ "$AUDIT_LINES" -lt 48 ]]; then
  echo "STOP: partial audit ($AUDIT_LINES lines); need clean restart"
  exit 7
fi

HERMETIC=(env -i
  HOME="$HOME"
  PATH="$PATH"
  USER="${USER:-ubuntu}"
  TMPDIR="${TMPDIR:-/tmp}"
  CURSOR_API_KEY="${CURSOR_API_KEY:?CURSOR_API_KEY required}"
  R2_METHOD_ARM=A
)

WAVE2_HUNG_COUNT="$(grep -c '^WAVE_2_HUNG_KILLED' "$RUN_LOG" 2>/dev/null || true)"
echo "wave2_hung_strikes=${WAVE2_HUNG_COUNT}"
if [[ "$WAVE2_HUNG_COUNT" -ge 2 ]]; then
  echo "STOP: wave2 second-hang policy (already ${WAVE2_HUNG_COUNT} WAVE_2_HUNG_KILLED); do not restart whole wave"
  exit 10
fi

CAP_RUNNER="$REPO_ROOT/exam-artifacts/r1-packb-a/run-wave-slots-capped.sh"
chmod +x "$CAP_RUNNER"

for wave_idx in 1 2; do
  readarray -t WAVE_META < <(python3 - <<PY
import json
plan=json.load(open("$PLAN"))
w=plan["waves"][$wave_idx]
print(w["iteration"])
print(w["outputJson"])
PY
)
  ITER="${WAVE_META[0]}"
  OUT_REL="${WAVE_META[1]}"
  OUT="$REPO_ROOT/$OUT_REL"
  WAVE_RESULTS=0
  if [[ -f "$OUT" ]]; then
    WAVE_RESULTS="$(python3 -c "import json; print(len(json.load(open('$OUT')).get('results',[])))" 2>/dev/null || echo 0)"
  fi
  EXPECT_AUDIT=$((48 * ITER))
  CURRENT_AUDIT="$(wc -l <"$AUDIT" | tr -d ' ')"
  if [[ "$WAVE_RESULTS" -eq 48 ]] && [[ "$CURRENT_AUDIT" -ge "$EXPECT_AUDIT" ]]; then
    echo "WAVE_${ITER}_SKIP complete json+audit"
    continue
  fi
  if [[ "$ITER" -eq 2 ]] && [[ "$WAVE_RESULTS" -lt 48 ]]; then
    rm -f "$OUT"
    CURRENT_AUDIT="$(wc -l <"$AUDIT" | tr -d ' ')"
    if [[ "$CURRENT_AUDIT" -gt 48 ]]; then
      echo "STOP: partial wave2 audit without complete json; manual fix required"
      exit 12
    fi
  fi
  echo "WAVE_${ITER}_START $(date -u +%Y-%m-%dT%H:%M:%SZ) mode=per_slot_cap_15m"
  bash "$CAP_RUNNER" "$wave_idx" "$SYSPROMPT_CHARS" "$SYSPROMPT_SHA" "$MODEL_JSON" "$FIX_SHA_FULL"
  WAVE_RESULTS="$(python3 -c "import json; print(len(json.load(open('$OUT')).get('results',[])))")"
  CURRENT_AUDIT="$(wc -l <"$AUDIT" | tr -d ' ')"
  echo "WAVE_${ITER}_WROTE $OUT_REL results=${WAVE_RESULTS} audit_lines=${CURRENT_AUDIT}"
done

FINAL_LINES="$(wc -l <"$AUDIT" | tr -d ' ')"
echo "=== R1-A2 pack B run complete $(date -u +%Y-%m-%dT%H:%M:%SZ) audit_lines=$FINAL_LINES ==="
if [[ "$FINAL_LINES" -ne 144 ]]; then
  echo "STOP: expected 144 audit lines, got $FINAL_LINES"
  exit 8
fi
