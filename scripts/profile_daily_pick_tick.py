#!/usr/bin/env python3
"""Profile one daily-pick scheduler tick locally (stage timings to stderr).

Usage (from repo root, venv active):
  python scripts/profile_daily_pick_tick.py
  DAILY_PICK_STAGE_TIMING=on python scripts/profile_daily_pick_tick.py --force
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")


def main() -> int:
    parser = argparse.ArgumentParser(description="Profile daily pick tick stages")
    parser.add_argument("--force", action="store_true", help="Regenerate today's pick")
    args = parser.parse_args()
    os.environ.setdefault("DAILY_PICK_STAGE_TIMING", "on")

    from internal.council.daily_pick_engine import get_or_create_today_pick
    from internal.council.pick_scheduler import _load_capped_subnets, _market_context

    started = time.perf_counter()
    with_stage = time.perf_counter()
    subnets = _load_capped_subnets()
    load_ms = (time.perf_counter() - with_stage) * 1000
    with_stage = time.perf_counter()
    ctx = _market_context(subnets)
    ctx_ms = (time.perf_counter() - with_stage) * 1000

    with_stage = time.perf_counter()
    payload = get_or_create_today_pick(subnets, ctx, force=args.force)
    pick_ms = (time.perf_counter() - with_stage) * 1000
    total_ms = (time.perf_counter() - started) * 1000

    print(
        f"profile summary universe={len(subnets)} "
        f"load_subnets={int(load_ms)}ms market_context={int(ctx_ms)}ms "
        f"pick_work={int(pick_ms)}ms total={int(total_ms)}ms "
        f"action={payload.get('action')} scheduler_hold={payload.get('scheduler_hold')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
