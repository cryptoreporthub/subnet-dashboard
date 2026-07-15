#!/usr/bin/env bash
# F7 — custom domain checklist (human; needs flyctl + registrar access).
# See DEPLOY.md. Run: ./scripts/f7-custom-domain.sh
set -euo pipefail

APP="${FLY_APP:-subnet-dashboard}"
HOST="${CUSTOM_DOMAIN:-dashboard.cryptoreporthub.com}"

echo "F7 custom domain — $HOST → $APP.fly.dev"
echo
echo "1) At registrar, add DNS:"
echo "   CNAME $HOST → $APP.fly.dev"
echo
echo "2) On Fly (after flyctl auth login):"
echo "   flyctl certs add $HOST --app $APP"
echo "   flyctl certs show $HOST --app $APP    # wait until Ready"
echo
echo "3) Optional — set canonical base URL for meta/OG tags:"
echo "   flyctl secrets set APP_BASE_URL=https://$HOST --app $APP"
echo
echo "4) Verify:"
echo "   CUSTOM_DOMAIN=$HOST ./scripts/verify_prod.sh"
echo

if command -v flyctl >/dev/null 2>&1; then
  echo "== flyctl certs show (if already added) =="
  flyctl certs show "$HOST" --app "$APP" 2>/dev/null || echo "(cert not added yet — run step 2)"
else
  echo "(flyctl not installed — follow DEPLOY.md manually)"
fi
