#!/usr/bin/env bash
# G0 — 390px phone QA smoke (SSR + no eternal Loading on Tier-1 brain surfaces).
set -euo pipefail

BASE="${APP_BASE_URL:-https://subnet-dashboard.fly.dev}"

echo "== G0 phone QA @ $BASE =="

html_tmp="$(mktemp)"
trap 'rm -f "$html_tmp"' EXIT
curl -fsS --max-time 45 "$BASE/" -o "$html_tmp"

python3 - "$html_tmp" <<'PY'
import pathlib
import sys
html = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8", errors="replace")
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
    ("hour watch rib", 'id="hour-watch-now"' in html),
]
failed = [name for name, ok in checks if not ok]
for name, ok in checks:
    print(("PASS" if ok else "FAIL") + ":", name)
if failed:
    raise SystemExit("G0 failed: " + ", ".join(failed))
print("G0 phone QA SSR checks OK")
PY

if curl -fsS --max-time 25 "$BASE/api/daily-pick" 2>/dev/null | python3 -c "import json,sys; d=json.load(sys.stdin); assert d.get('action'); print('daily-pick OK:', d.get('action'))"; then
  :
else
  echo "WARN: daily-pick timeout or invalid JSON (prod may be warming)"
fi

echo "== SS-TG W0 markers =="
python3 - "$html_tmp" <<'PY2'
import pathlib, sys
html = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8", errors="replace")
checks = [
    ("section-message-intel", 'id="section-message-intel"' in html),
    ("subnet summers brand", "Subnet Summers" in html),
    ("t.me link", "t.me/OfficialSubnetSummer" in html),
    ("yesterday card", "message-intel-yesterday" in html),
    ("hc strip", "message-intel-hc-strip" in html),
    ("proof band", "message-intel-proof" in html),
]
failed = [n for n, ok in checks if not ok]
for n, ok in checks:
    print(("PASS" if ok else "FAIL") + ":", n)
if failed:
    raise SystemExit("SS-TG failed: " + ", ".join(failed))
print("SS-TG W0 markers OK")
PY2
if curl -fsS --max-time 25 -o /tmp/g0_pump.json "$BASE/api/pump-alerts"; then
  python3 -c "
import json
d=json.load(open('/tmp/g0_pump.json'))
status = d.get('status')
alerts = d.get('alerts') or []
count = d.get('count', len(alerts))
print('pump-alerts OK: status=%s count=%s desk=%s' % (status, count, d.get('desk')))
if status == 'timeout':
    print('WARN: pump-alerts API timeout — homepage pump desk SSR is the G0 gate')
elif alerts and not d.get('desk'):
    assert all('triad' in a for a in alerts), 'missing triad on full alert rows'
"
else
  echo "WARN: pump-alerts API curl failed — homepage pump desk SSR is the G0 gate"
fi

echo "G0 complete"
