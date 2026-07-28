#!/usr/bin/env bash
# Generate WRITE_API_TOKEN and set on Fly (optional prod hardening — audit Phase A).
set -euo pipefail

APP="${FLY_APP:-subnet-dashboard}"
TOKEN="${1:-}"

if [ -z "$TOKEN" ]; then
  if command -v openssl >/dev/null 2>&1; then
    TOKEN="$(openssl rand -hex 32)"
  else
    TOKEN="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
  fi
  echo "Generated WRITE_API_TOKEN (save this — shown once):"
  echo "$TOKEN"
fi

if ! command -v flyctl >/dev/null 2>&1; then
  echo "flyctl not found — set manually:"
  echo "  flyctl secrets set WRITE_API_TOKEN='$TOKEN' --app $APP"
  exit 1
fi

flyctl secrets set "WRITE_API_TOKEN=$TOKEN" --app "$APP"
echo "WRITE_API_TOKEN set on $APP. Contract tests / local dev stay open when env unset."
