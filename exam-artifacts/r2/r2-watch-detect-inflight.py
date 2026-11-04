#!/usr/bin/env python3
"""Print in-flight plan idx and seconds since SLOT_START if no matching SLOT_END yet."""
from __future__ import annotations

import re
import sys
from datetime import datetime, timezone
from pathlib import Path

LOG = Path(sys.argv[1])
if not LOG.is_file():
    print("inflight_idx=")
    print("inflight_sec=0")
    sys.exit(0)

starts: list[tuple[int, str, int]] = []
ends: set[tuple[int, int]] = set()
for i, line in enumerate(LOG.read_text(errors="replace").splitlines()):
    m = re.search(r"SLOT_START idx=(\d+) eval_id=.* at=([\d\-T:Z]+)", line)
    if m:
        starts.append((int(m.group(1)), m.group(2), i))
    m = re.search(r"SLOT_END idx=(\d+) ", line)
    if m:
        ends.add((int(m.group(1)), i))

if not starts:
    print("inflight_idx=")
    print("inflight_sec=0")
    sys.exit(0)

idx, started_at, start_line = starts[-1]
if any(eidx == idx and eline > start_line for eidx, eline in ends):
    print("inflight_idx=")
    print("inflight_sec=0")
    sys.exit(0)

t0 = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
sec = int((datetime.now(timezone.utc) - t0).total_seconds())
print(f"inflight_idx={idx}")
print(f"inflight_sec={sec}")
print(f"inflight_started_at={started_at}")
