#!/usr/bin/env bash
# G0 — 390px phone QA smoke (SSR + no eternal Loading on Tier-1 brain surfaces).
set -euo pipefail

BASE="${APP_BASE_URL:-https://subnet-dashboard.fly.dev}"

echo "== G0 phone QA @ $BASE =="

html="$(curl -fsS --max-time 45 "$BASE/")"

python3 - <<'PY' "$html"
import sys
html = sys.argv[1]
checks = [
    ("hydrate flag", "dataset.hydrate='1'" in html or 'data-hydrate="1"' in html),
    ("hero dossier", 'id="k3-dossier"' in html),
    ("living focus section", 'id="section-living-focus"' in html),
    ("LF four-beat sub", "Focus · Contest · Prove it · Watch us update" in html),
    ("brain letter section", 'id="section-brain-letter"' in html),
    ("proof band", "section-proof-band" in html),
    ("pump desk section", 'id="section-pump-alert"' in html),
    ("no pump hydrate placeholder", "Pump desk loads after hydrate" not in html),
    ("no council convening placeholder", "Council is convening" not in html),
    ("no eternal judge loading", "Loading judge scores" not in html),
    ("no backtest warming", "Backtest warming up" not in html),
    ("dual judge labels", "Lane judges" in html and "Council weights (soul map)" in html),
    ("track record weight nudge hook", 'id="k3-weight-nudge-line"' in html),
    ("no story path warming", "Story path warming up" not in html),
]
failed = [name for name, ok in checks if not ok]
for name, ok in checks:
    print(("PASS" if ok else "FAIL") + ":", name)
if failed:
    raise SystemExit("G0 failed: " + ", ".join(failed))
print("G0 phone QA SSR checks OK")
PY

curl -fsS --max-time 20 "$BASE/api/daily-pick" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d.get('action'); print('daily-pick OK:', d.get('action'))"
curl -fsS --max-time 25 "$BASE/api/pump-alerts" | python3 -c "import json,sys; d=json.load(sys.stdin); print('pump-alerts OK: count=', d.get('count', len(d.get('alerts') or []))); alerts=d.get('alerts') or []; assert all('triad' in a for a in alerts), 'missing triad on alert rows'"

echo "G0 complete"
