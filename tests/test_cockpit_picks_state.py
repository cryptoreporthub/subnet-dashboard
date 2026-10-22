"""An empty top-picks payload must show a status message, never a blank section or live scoring."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

HYDRATE = Path("static/js/cockpit_hydrate.js")

SCRIPT = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[1], 'utf8');
const start = src.indexOf('function picksViewFor(');
if (start < 0) throw new Error('picksViewFor missing');
let depth = 0, end = -1;
for (let i = src.indexOf('{', start); i < src.length; i++) {
  if (src[i] === '{') depth++;
  if (src[i] === '}' && --depth === 0) { end = i + 1; break; }
}
const picksViewFor = new Function(src.slice(start, end) + '; return picksViewFor;')();
const PICK = [{ netuid: 1 }];
const cases = [
  [{ hour_picks: [], day_picks: [], status: 'pending_snapshot' }, false, 'message', /missing or out of date/],
  [{ hour_picks: [], day_picks: [], status: 'busy' }, false, 'message', /another viewer/],
  [{ hour_picks: [], day_picks: [], status: 'timeout' }, false, 'message', /timed out/],
  [{ hour_picks: [], day_picks: [], error: 'boom' }, false, 'message', /failed to load/],
  [{ hour_picks: [], day_picks: [], status: 'stale_snapshot' }, false, 'message', /No picks available/],
  [{ hour_picks: null, day_picks: [], status: 'busy' }, false, 'message', /another viewer/],
  [{ hour_picks: PICK, day_picks: [] }, false, 'render', null],
  [{ hour_picks: [], day_picks: PICK, status: 'timeout' }, false, 'render', null],
  [{ hour_picks: [], day_picks: [] }, false, 'message', /No picks available/],
  [null, false, 'fallback', null],
  [{}, false, 'fallback', null],
  [{ hour_picks: [], day_picks: [], status: 'pending_snapshot' }, true, 'skip', null],
  [{ hour_picks: PICK, day_picks: [] }, true, 'skip', null],
];
for (const [payload, connected, want, text] of cases) {
  const got = picksViewFor(payload, connected);
  const label = JSON.stringify(payload) + ' connected=' + connected;
  if (got.state !== want) throw new Error(label + ' -> ' + got.state + ', want ' + want);
  if (text && !text.test(got.message)) throw new Error(label + ' message ' + got.message);
}
"""


def test_empty_picks_payloads_get_a_message_not_a_blank_or_live_scoring():
    node = shutil.which("node")
    if not node:
        pytest.fail("node is required for this test")
    result = subprocess.run(
        [node, "-e", SCRIPT, str(HYDRATE)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr

