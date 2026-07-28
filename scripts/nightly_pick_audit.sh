#!/usr/bin/env bash
# Nightly pick selection audit — evidence loop (Python scorer, not LLM).
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ -f .venv/bin/activate ]]; then
  # shellcheck source=/dev/null
  source .venv/bin/activate
fi
export PYTHONPATH="${PYTHONPATH:-}:$(pwd)"
python - <<'PY'
import json
import sys

from internal.council.pick_audit_scheduler import _load_subnets_and_context
from internal.council.pick_selection_audit import run_audit_today, audit_path_for_date, _today_str

subnets, ctx = _load_subnets_and_context()
if not subnets:
    print("WARN: no subnets loaded — audit uses empty universe", file=sys.stderr)
payload = run_audit_today(subnets, ctx, save=True)
path = audit_path_for_date(payload.get("pick_date") or _today_str())
print(json.dumps({"path": path, "verdict": payload.get("verdict"), "category": payload.get("category")}, indent=2))
if payload.get("verdict") == "MISS":
    sys.exit(2)
PY
