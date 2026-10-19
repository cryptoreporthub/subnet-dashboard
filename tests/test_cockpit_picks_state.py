"""The cockpit must say so when the score snapshot is pending, and must not score live."""

from __future__ import annotations

import subprocess
from pathlib import Path

HYDRATE = Path("static/js/cockpit_hydrate.js")

SCRIPT = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[1], 'utf8');
const start = src.indexOf('function picksStateFor(');
if (start < 0) throw new Error('picksStateFor missing');
let depth = 0, end = -1;
for (let i = src.indexOf('{', start); i < src.length; i++) {
  if (src[i] === '{') depth++;
  if (src[i] === '}' && --depth === 0) { end = i + 1; break; }
}
const picksStateFor = new Function(src.slice(start, end) + '; return picksStateFor;')();
const cases = [
  [{ hour_picks: [], day_picks: [], status: 'pending_snapshot' }, false, 'pending'],
  [{ hour_picks: [{ netuid: 1 }], day_picks: [] }, false, 'render'],
  [null, false, 'fallback'],
  [{}, false, 'fallback'],
  [{ hour_picks: [], day_picks: [], status: 'pending_snapshot' }, true, 'skip'],
  [{ hour_picks: [{ netuid: 1 }], day_picks: [] }, true, 'skip'],
];
for (const [payload, connected, want] of cases) {
  const got = picksStateFor(payload, connected);
  if (got !== want) throw new Error(JSON.stringify(payload) + ' connected=' + connected + ' -> ' + got + ', want ' + want);
}
"""


def test_pending_snapshot_shows_pending_instead_of_blank_or_live_scoring():
    result = subprocess.run(
        ["node", "-e", SCRIPT, str(HYDRATE)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_pending_state_marks_the_picks_section():
    src = HYDRATE.read_text()
    block = src[src.index("var picksState = picksStateFor("):]
    pending = block[: block.index("return;") + len("return;")]
    assert "markSectionFailed('section-picks'" in pending
