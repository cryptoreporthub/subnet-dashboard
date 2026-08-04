#!/usr/bin/env bash
# Post-deploy cache warm — serial, light paths first (avoid cold-machine wedge).
set -euo pipefail

BASE="${APP_BASE_URL:-https://subnet-dashboard.fly.dev}"
PATHS=(
  "/health"
  "/api/learning/health"
  "/api/data-freshness"
  "/api/portfolio/status"
)
# Homepage SSR can wedge a cold single-worker VM — leave it to real traffic later.
OPTIONAL_PATHS=(
  "/"
  "/api/learning/stats"
  "/api/daily-pick"
)

echo "== warm $BASE (serial) =="
fail=0
for path in "${PATHS[@]}"; do
  code=$(curl -sS -m 25 -o /tmp/warm_body.txt -w "%{http_code}" "$BASE$path" || echo 000)
  echo "$path -> HTTP $code"
  if [ "$code" != "200" ] && [ "$code" != "304" ]; then
    fail=1
    echo "warm_prod: aborting optional warm after required path failure"
    break
  fi
  sleep 2
done

if [ "$fail" -eq 0 ]; then
  for path in "${OPTIONAL_PATHS[@]}"; do
    code=$(curl -sS -m 15 -o /tmp/warm_body.txt -w "%{http_code}" "$BASE$path" || echo 000)
    echo "$path -> HTTP $code (optional)"
    sleep 2
  done
fi

if [ "$fail" -ne 0 ]; then
  echo "warm_prod: one or more required endpoints did not return 200"
  exit 1
fi
echo "warm_prod OK"
