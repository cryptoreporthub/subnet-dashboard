#!/usr/bin/env python3
"""CI gate: image seed must exist and pass quality gates (#1479 PR-B)."""

from __future__ import annotations

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from internal.council.score_snapshots import SCORE_SNAPSHOT_SEED_PATH, is_complete_snapshot  # noqa: E402
from internal.council.seed_quality import validate_shipped_seed  # noqa: E402


def main() -> int:
    path = SCORE_SNAPSHOT_SEED_PATH
    if not os.path.isfile(path):
        print(f"missing seed: {path}", file=sys.stderr)
        return 2
    with open(path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not is_complete_snapshot(payload):
        print(f"seed fails is_complete_snapshot: {path}", file=sys.stderr)
        return 2
    ok, reason = validate_shipped_seed(payload)
    if not ok:
        print(f"seed fails validate_shipped_seed ({reason}): {path}", file=sys.stderr)
        return 2
    if not path.startswith("data_seeds"):
        print(f"seed must live under data_seeds/, got {path}", file=sys.stderr)
        return 2
    print(f"seed ok: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
