#!/usr/bin/env python3
"""Soul-map compaction — Runbook v4 Phase 2 (Steps A-E + settle recheck).

Trims the inactive feedback_logs relic (429 fossil entries, 22.1MB) from
data/soul_map.json on the live Fly machine. Read-only on disk until --execute.

Usage (via fly ssh console / SSH workflow, cwd=/app):
    python scripts/compact_soul_map.py --dry-run
    python scripts/compact_soul_map.py --execute \
        --backup /app/data/soul_map.json.bak-<PINNED_TIMESTAMP>

Exit codes: 0 ok | 2 dry-run/arg failure | 3 verify failed (restored)
            4 quiescence gate (nothing written) | 5 settle recheck failed (restored)
"""

from __future__ import annotations

import argparse
import copy
import filecmp
import json
import os
import shutil
import sys
import time

DEFAULT_PATH = "/app/data/soul_map.json"
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

STATIC_REQUIRED_KEYS = [
    "expert_weights",
    "soul_map_state",
    "prediction_resolver_scheduler",
    "adversarial_state",
    "simivision_convictions",
]
FEEDBACK_LOGS_KEEP = 10
SIZE_ENVELOPE = (400_000, 1_500_000)   # ~402KB = key dropped | ~24.2MB = no-op/reverted
CACHE_TTL_SECONDS = 5                  # internal/store/soul_map_io.py _CACHE_TTL default
SETTLE_SECONDS = 12                    # TTL + margin > max in-flight 24MB dump duration


def _load_disk(path: str):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)  # raises on invalid JSON - caller handles


def _mutator(blob: dict) -> None:
    logs = blob.get("feedback_logs")
    if isinstance(logs, list) and len(logs) > FEEDBACK_LOGS_KEEP:
        blob["feedback_logs"] = logs[-FEEDBACK_LOGS_KEEP:]
    # trim-only: corrupt/non-list key is preserved as-is (no silent drop)


def _assert_envelope(size: int) -> bool:
    return SIZE_ENVELOPE[0] <= size <= SIZE_ENVELOPE[1]


def dry_run(path: str) -> int:
    blob = _load_disk(path)
    missing = [k for k in STATIC_REQUIRED_KEYS if k not in blob]
    logs = blob.get("feedback_logs")
    sim = copy.deepcopy(blob)
    _mutator(sim)
    projected = len(json.dumps(sim, indent=2).encode("utf-8"))
    print("TOP_LEVEL_KEY_INVENTORY:", json.dumps(sorted(blob.keys())))
    print(f"FEEDBACK_LOGS_LEN: {len(logs) if isinstance(logs, list) else 'NON-LIST'}")
    print(f"CURRENT_SIZE_BYTES: {os.path.getsize(path)}")
    print(f"PROJECTED_SIZE_BYTES: {projected}")
    if missing:
        print(f"DRY_RUN_FAILED missing_required_keys={missing}")
        return 2
    if not isinstance(logs, list) or len(logs) <= FEEDBACK_LOGS_KEEP:
        print("DRY_RUN_FAILED feedback_logs must be a list with len > 10 (nothing to compact)")
        return 2
    if not _assert_envelope(projected):
        print("DRY_RUN_FAILED projected size outside envelope - re-measure before execute")
        return 2
    print("DRY_RUN_SUCCESS")
    return 0


def execute(path: str, backup: str) -> int:
    # Pinned backup integrity - byte-exact, never globbed
    if not (os.path.exists(backup) and filecmp.cmp(path, backup, shallow=False)):
        print(f"EXECUTE_ABORTED backup_missing_or_mismatch={backup}")
        return 3

    pre = _load_disk(path)
    inventory = set(pre.keys())
    missing_pre = [k for k in STATIC_REQUIRED_KEYS if k not in inventory]
    logs_pre = pre.get("feedback_logs")
    if missing_pre or not isinstance(logs_pre, list) or len(logs_pre) <= FEEDBACK_LOGS_KEEP:
        print(f"EXECUTE_ABORTED precondition_failed missing={missing_pre} "
              f"logs_len={len(logs_pre) if isinstance(logs_pre, list) else 'NON-LIST'}")
        return 3

    # Pre-flight envelope on a simulated post-mutator blob - no write yet
    sim = copy.deepcopy(pre)
    _mutator(sim)
    projected = len(json.dumps(sim, indent=2).encode("utf-8"))
    if not _assert_envelope(projected):
        print(f"EXECUTE_ABORTED projected_size_outside_envelope projected={projected}")
        return 3

    # Step A - quiescence gate: last disk write must be older than the TTL
    age = time.time() - os.path.getmtime(path)
    if age < CACHE_TTL_SECONDS + 1:
        print(f"EXECUTE_ABORTED quiescence_gate last_write_age_s={age:.1f} "
              f"need>={CACHE_TTL_SECONDS + 1}")
        return 4

    def _restore_and_exit(reason: str, code: int) -> int:
        shutil.copy2(backup, path)
        print(f"COMPACTION_FAILED_RESTORED reason={reason}")
        return code

    # Canonical write path. NOTE: this script is a separate process from the
    # server - the RMW lock is process-local and cannot see us; cross-process
    # safety comes from the quiescence gate + Step B-prime settle recheck below.
    sys.path.insert(0, REPO_ROOT)
    from internal.store.soul_map_io import write_soul_map
    write_soul_map(_mutator, path=path)

    # Step B - direct-from-disk parse (NOT read_soul_map: 5s TTL cache)
    try:
        post = _load_disk(path)
    except Exception as exc:
        return _restore_and_exit(f"post_write_json_load_failed ({exc})", 3)

    # Step C - static keys + dynamic no-drop (every pre-write key survives)
    missing_post = [k for k in STATIC_REQUIRED_KEYS if k not in post]
    dropped = sorted(inventory - set(post.keys()))
    if missing_post or dropped:
        return _restore_and_exit(f"schema_check missing={missing_post} dropped={dropped}", 3)

    # Step D - payload + size assertions
    logs = post.get("feedback_logs")
    size = os.path.getsize(path)
    if not isinstance(logs, list) or len(logs) > FEEDBACK_LOGS_KEEP:
        return _restore_and_exit(
            f"feedback_logs_invalid len={len(logs) if isinstance(logs, list) else 'NON-LIST'}", 3)
    if not _assert_envelope(size):
        return _restore_and_exit(f"size_outside_envelope size={size}", 3)

    # Step B-prime - settle recheck: catches a cross-process in-flight clobber
    # (server write that read pre-compaction disk and lands after our replace).
    # A benign small write here is fine - it proves the server re-read the
    # compacted disk (cache expired) and the resurrection vector is closed.
    time.sleep(SETTLE_SECONDS)
    try:
        settle = _load_disk(path)
        settle_size = os.path.getsize(path)
    except Exception as exc:
        return _restore_and_exit(f"settle_recheck_parse_failed ({exc})", 5)
    missing_settle = [k for k in STATIC_REQUIRED_KEYS if k not in settle]
    dropped_settle = sorted(inventory - set(settle.keys()))
    logs_settle = settle.get("feedback_logs")
    if (not _assert_envelope(settle_size) or missing_settle or dropped_settle
            or not isinstance(logs_settle, list) or len(logs_settle) > FEEDBACK_LOGS_KEEP):
        return _restore_and_exit(
            f"settle_recheck_detected_reversion size_before={size} size_after={settle_size}", 5)

    print(f"PRE_RESTART_VERIFICATION_PASSED bytes={settle_size} "
          f"feedback_logs_len={len(logs_settle)}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--execute", action="store_true")
    ap.add_argument("--path", default=DEFAULT_PATH)
    ap.add_argument("--backup", default=None)
    args = ap.parse_args()

    if not os.path.exists(args.path):
        print(f"ARG_ERROR soul_map not found at {args.path}")
        return 2
    try:
        if args.dry_run and not args.execute:
            return dry_run(args.path)
        if args.execute and not args.dry_run:
            if not args.backup:
                print("ARG_ERROR --execute requires --backup <pinned .bak path>")
                return 2
            return execute(args.path, args.backup)
    except json.JSONDecodeError as exc:
        print(f"FATAL live file is not valid JSON: {exc}")
        return 2
    print("ARG_ERROR choose --dry-run or --execute")
    return 2


if __name__ == "__main__":
    sys.exit(main())
