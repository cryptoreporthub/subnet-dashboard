#!/usr/bin/env python3
"""Compare pytest junit XML files — failing testcase IDs per side."""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def _ids(path: Path) -> set[str]:
    root = ET.parse(path).getroot()
    out: set[str] = set()
    for case in root.iter("testcase"):
        name = case.get("name") or ""
        cls = case.get("classname") or ""
        tid = f"{cls}::{name}" if cls else name
        failed = case.find("failure") is not None or case.find("error") is not None
        if failed:
            out.add(tid)
    return out


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: pytest_junit_setdiff.py main.xml head.xml", file=sys.stderr)
        return 2
    main_p, head_p = Path(sys.argv[1]), Path(sys.argv[2])
    main_ids = _ids(main_p)
    head_ids = _ids(head_p)
    new_on_head = sorted(head_ids - main_ids)
    fixed = sorted(main_ids - head_ids)
    print(f"main_failed={len(main_ids)} head_failed={len(head_ids)}")
    print(f"new_on_head={len(new_on_head)} fixed_on_head={len(fixed)}")
    if new_on_head:
        print("NEW_ON_HEAD:")
        for tid in new_on_head:
            print(tid)
    if fixed:
        print("FIXED_ON_HEAD:")
        for tid in fixed[:30]:
            print(tid)
        if len(fixed) > 30:
            print(f"... +{len(fixed) - 30} more")
    return 1 if new_on_head else 0


if __name__ == "__main__":
    raise SystemExit(main())
