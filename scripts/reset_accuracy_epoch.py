#!/usr/bin/env python3
"""Archive predictions.json and start a fresh accuracy epoch (Acc-0)."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import sys
import uuid

from internal.learning.ledger_heal import archive_predictions_epoch


def main() -> int:
    parser = argparse.ArgumentParser(description="Archive predictions and reset accuracy epoch")
    parser.add_argument(
        "--no-heal",
        action="store_true",
        help="Skip daily-pick ledger backfill after reset",
    )
    parser.add_argument("--request-id", help="Reuse an explicit reset request ID")
    parser.add_argument("--new", action="store_true", help="Start a new reset request")
    args = parser.parse_args()
    os.makedirs("data", exist_ok=True)
    pending = "data/.pending_reset_id"
    with open(f"{pending}.lock", "a+", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        if args.request_id:
            request_id = args.request_id
        elif os.path.exists(pending) and not args.new:
            with open(pending, encoding="utf-8") as handle:
                request_id = handle.read().strip()
        else:
            request_id = str(uuid.uuid4())
        temporary = f"{pending}.{uuid.uuid4().hex}.tmp"
        with open(temporary, "x", encoding="utf-8") as handle:
            handle.write(request_id)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, pending)
        descriptor = os.open("data", os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        summary = archive_predictions_epoch(
            reset_request_id=request_id, re_heal_daily=not args.no_heal
        )
        if summary.get("ok"):
            os.unlink(pending)
        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
    print(json.dumps(summary, indent=2))
    return 0 if summary.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
