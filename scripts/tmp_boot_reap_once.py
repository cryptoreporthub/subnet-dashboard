#!/usr/bin/env python3
"""CLI for tmp boot reaper — safe to run via fly machine exec."""
from __future__ import annotations

import os
import sys


def main() -> int:
    dry = os.environ.get("TMP_BOOT_REAP_DRY", "").strip().lower() in ("1", "true", "yes", "on")
    from internal.tmp_boot_reaper import reap_stale_tmp_files

    count, paths = reap_stale_tmp_files(dry_run=dry)
    print(f"count={count} dry_run={dry}")
    for path in paths[:50]:
        print(path)
    if len(paths) > 50:
        print(f"... and {len(paths) - 50} more")
    return 0


if __name__ == "__main__":
    sys.exit(main())
