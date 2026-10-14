#!/usr/bin/env python3
"""CLI for tmp boot reaper — safe to run via fly machine exec."""
from __future__ import annotations

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


def main() -> int:
    dry = os.environ.get("TMP_BOOT_REAP_DRY", "").strip().lower() in ("1", "true", "yes", "on")
    from internal.tmp_boot_reaper import run_machine_start_reap

    count, paths = run_machine_start_reap(dry_run=dry)
    print(f"count={count} dry_run={dry}")
    for path in paths[:50]:
        print(path)
    if len(paths) > 50:
        print(f"... and {len(paths) - 50} more")
    return 0


if __name__ == "__main__":
    sys.exit(main())
