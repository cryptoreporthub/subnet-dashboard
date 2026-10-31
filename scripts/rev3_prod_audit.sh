#!/usr/bin/env bash
# REV3 closeout audit — read-only prod checks (volume row + dry_run recover + logs).
# Does NOT POST resolver/run or mutate predictions/weights.
set -euo pipefail
APP="${FLY_APP:-subnet-dashboard}"
DEPLOY_SHA="${REV3_DEPLOY_SHA:-35b1bf34f5e0af086cfbb1910567ef9796ca49ef}"
ROW_ID="${REV3_ROW_ID:-dd13cfb298}"

echo "=== REV3 prod audit deploy_sha=${DEPLOY_SHA} row=${ROW_ID} ==="

echo "=== SENTRY_RELEASE on machine ==="
ACTUAL="$(flyctl ssh console -a "$APP" -C 'printenv SENTRY_RELEASE' 2>/dev/null | tr -d '\r\n' || true)"
echo "expected=${DEPLOY_SHA}"
echo "actual=${ACTUAL}"
if [ -n "$ACTUAL" ] && [ "$ACTUAL" != "$DEPLOY_SHA" ]; then
  echo "WARN: SENTRY_RELEASE mismatch (may be older deploy finishing)"
fi

MID="$(flyctl machines list -a "$APP" --json | jq -r '[.[] | select(.state=="started" or .state=="running") | select(((.process_group // .config.process_group // "web") == "web"))][0].id // empty')"
if [ -z "$MID" ] || [ "$MID" = "null" ]; then
  MID="$(flyctl machines list -a "$APP" --json | jq -r '[.[] | select(.state=="started" or .state=="running")][0].id // empty')"
fi
echo "probe_machine=${MID}"

_remote_python() {
  local py="$1"
  local b64
  b64=$(printf '%s' "$py" | base64 -w0 2>/dev/null || printf '%s' "$py" | base64 | tr -d '\n')
  flyctl machine exec "$MID" -a "$APP" --timeout 120 \
    "bash -lc 'cd /app && python3 -c \"import base64; exec(base64.b64decode(\\\"${b64}\\\").decode())\"'"
}

AUDIT_PY="import json, hashlib
DEPLOY = \"${DEPLOY_SHA}\"
ROW = \"${ROW_ID}\"
path = \"data/predictions.json\"
raw = open(path, \"rb\").read()
ledger_hash = hashlib.sha256(raw).hexdigest()
data = json.loads(raw.decode())
found = {}
for bucket in (\"predictions\", \"resolved\"):
    for p in data.get(bucket, []) or []:
        if isinstance(p, dict) and p.get(\"id\") == ROW:
            found[bucket] = {k: p.get(k) for k in (
                \"id\", \"status\", \"outcome\", \"shadow\", \"counterfactual\",
                \"price_data_unavailable\", \"retirement_reason\", \"resolve_at\",
                \"horizon_hours\", \"resolved_at\", \"historical_hydration_attempted\",
                \"side_effect_warnings\",
            )}
stats = data.get(\"stats\") or {}
missing = [r.get(\"id\") for r in (data.get(\"resolved\") or []) if r.get(\"retirement_reason\") == \"missing_price_at_horizon\"]
print(json.dumps({
    \"deploy_sha\": DEPLOY,
    \"predictions_json_sha256\": ledger_hash,
    \"row\": found,
    \"stats_pending\": stats.get(\"pending\"),
    \"stats_price_data_unavailable\": stats.get(\"price_data_unavailable\"),
    \"missing_price_resolved_count\": len(missing),
    \"missing_price_sample_ids\": missing[:10],
}, indent=2))
"

RECOVER_PY='from internal.learning.expired_recovery import recover_expired_predictions
import json
print(json.dumps(recover_expired_predictions(dry_run=True), indent=2))
'

REGRADE_OBS='import json
from internal.learning.predictions_store import load_predictions
data = load_predictions()
resolved = data.get("resolved") or []
candidates = [r for r in resolved if isinstance(r, dict) and r.get("outcome") == "expired" and r.get("retirement_reason") == "missing_price_at_horizon"]
print(json.dumps({
  "observation_only": True,
  "regrade_candidate_count": len(candidates),
  "sample_ids": [r.get("id") for r in candidates[:10]],
  "note": "Did not invoke regrade_expired_predictions (would mutate resolved rows)",
}, indent=2))
'

echo "=== volume row + ledger hash (read-only) ==="
if [ -n "$MID" ]; then _remote_python "$AUDIT_PY" || true; else echo "WARN: no probe_machine; skip volume audit"; fi

echo "=== recover_expired_predictions dry_run=True (no ledger mutation) ==="
if [ -n "$MID" ]; then _remote_python "$RECOVER_PY" || true; else echo "WARN: no probe_machine; skip dry_run recover"; fi

echo "=== regrade observation-only (counts; no regrade_expired_predictions call) ==="
if [ -n "$MID" ]; then _remote_python "$REGRADE_OBS" || true; else echo "WARN: no probe_machine; skip regrade observation"; fi

echo "=== resolver / revive log lines (post-deploy window) ==="
flyctl logs -a "$APP" --no-tail 2>&1 \
  | grep -iE "resolver lifecycle|prediction_resolver|heavy_job_busy|cycle_in_flight|loop stall guard: resolver revive|revive_prediction_resolver|cycle_timeout|resolver tick stale|start_prediction_resolver" \
  | tail -300 || true

echo "=== public health ==="
curl -sS --max-time 20 "https://${APP}.fly.dev/api/learning/health" | python3 -m json.tool || true
