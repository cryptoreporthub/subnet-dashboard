#!/usr/bin/env python3
"""Full-63 false-PASS count (same rule as score-pre-five-pack.py / 18-scorer-freeze.md)."""
import json
import re
import sys
from pathlib import Path

STABLE_CLEAN = [
    f"{case}/{i}"
    for case in ("clean-extract-parser", "clean-tests-only", "clean-removal-log")
    for i in (1, 2, 3)
]


def slot_id(rid: str) -> str:
    m = re.search(r"/([^/]+)/(\d+)$", rid)
    return f"{m.group(1)}/{m.group(2)}" if m else rid


def posted_verdict(r: dict) -> str | None:
    for tc in r.get("toolCalls") or []:
        if tc.get("toolName") != "post_verdict" or tc.get("status") == "failed":
            continue
        inp = tc.get("input") or tc.get("args") or {}
        v = inp.get("verdict")
        if isinstance(v, str):
            return v
    return None


def det_has(r: dict, name: str) -> bool:
    for a in r.get("assertions") or []:
        if not a.get("passed") and (a.get("detail") or "").replace("det: ", "") == name:
            return True
    return False


def false_pass(r: dict) -> bool:
    pv = posted_verdict(r)
    if pv == "PASS":
        return True
    if det_has(r, "verdict-is-not-pass"):
        return True
    return False


def main() -> None:
    path = Path(sys.argv[1])
    results = json.loads(path.read_text()).get("results") or []
    by = {slot_id(r["id"]): r for r in results}
    fp = [s for s, r in by.items() if false_pass(r)]
    stable_fp = [s for s in STABLE_CLEAN if s in by and false_pass(by[s])]
    print(json.dumps({"total_false_pass": len(fp), "stable_clean_false_pass": stable_fp, "n_results": len(results)}, indent=2))


if __name__ == "__main__":
    main()
