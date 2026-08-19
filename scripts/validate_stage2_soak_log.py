#!/usr/bin/env python3
"""Validate Stage 2 soak log: probe cadence + SOAK PASSED (not just GHA exit 0)."""
from __future__ import annotations

import re
import sys
from datetime import datetime, timezone
from pathlib import Path


def validate(path: Path, max_gap: int = 360) -> tuple[bool, list[str]]:
    text = path.read_text(encoding="utf-8", errors="replace")
    lines: list[str] = []

    if "CADENCE GAP" in text:
        return False, ["log contains CADENCE GAP marker"]
    if "SOAK FAILED" in text:
        return False, ["log contains SOAK FAILED"]
    if "SOAK PASSED" not in text:
        return False, ["missing SOAK PASSED line"]

    pat = re.compile(r"^\[(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)\] probe (\d+)/(\d+)", re.M)
    matches = pat.findall(text)
    if not matches:
        return False, ["no probe timestamp lines found"]

    times = [
        datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        for ts, _, _ in matches
    ]
    nums = [int(n) for _, n, _ in matches]
    total = int(matches[-1][2])

    gaps_bad: list[str] = []
    for i in range(1, len(times)):
        gap = int((times[i] - times[i - 1]).total_seconds())
        if gap > max_gap:
            gaps_bad.append(f"probe {nums[i - 1]}→{nums[i]}: {gap}s > {max_gap}s")

    if gaps_bad:
        return False, gaps_bad
    if nums[-1] != total:
        return False, [f"incomplete: last probe {nums[-1]}/{total}"]
    if len(set(nums)) != len(nums):
        return False, ["duplicate probe numbers"]

    span = int((times[-1] - times[0]).total_seconds())
    ok_count = len(re.findall(r"^OK$", text, re.M))
    return True, [
        f"{len(matches)} probes, span={span}s, {ok_count} OK lines",
        f"first={matches[0][0]} last={matches[-1][0]}",
    ]


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: validate_stage2_soak_log.py <soak.log> [max_gap_seconds=360]", file=sys.stderr)
        return 2
    path = Path(sys.argv[1])
    max_gap = int(sys.argv[2]) if len(sys.argv) > 2 else 360
    ok, msgs = validate(path, max_gap)
    for m in msgs:
        print(("OK: " if ok else "FAIL: ") + m)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
