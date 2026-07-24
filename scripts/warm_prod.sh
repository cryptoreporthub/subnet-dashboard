#!/usr/bin/env bash
# Post-deploy cache warm — primes homepage shell + hot hydrate APIs.
set -euo pipefail

BASE="${APP_BASE_URL:-https://subnet-dashboard.fly.dev}"
PATHS=(
  "/health"
  "/"
  "/api/data-freshness"
  "/api/learning/stats"
  "/api/portfolio/status"
)
# daily-pick can wedge a cold machine; warm separately with a short deadline
OPTIONAL_PATHS=(
  "/api/daily-pick"
)

echo "== warm $BASE =="
fail=0
for path in "${PATHS[@]}"; do
  code=$(curl -sS -m 30 -o /tmp/warm_body.txt -w "%{http_code}" "$BASE$path" || echo 000)
  echo "$path -> HTTP $code"
  if [ "$code" != "200" ] && [ "$code" != "304" ]; then
    fail=1
  fi
done

for path in "${OPTIONAL_PATHS[@]}"; do
  code=$(curl -sS -m 10 -o /tmp/warm_body.txt -w "%{http_code}" "$BASE$path" || echo 000)
  echo "$path -> HTTP $code (optional)"
done

if [ "$fail" -ne 0 ]; then
  echo "warm_prod: one or more endpoints did not return 200"
  exit 1
fi
echo "warm_prod OK"
