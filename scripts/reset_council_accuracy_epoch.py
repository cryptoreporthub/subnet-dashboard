#!/usr/bin/env python3
"""Archive council grading ledger and start a fresh accuracy epoch.

Moves ``data/predictions.json`` resolved history to ``data/predictions_archive/``
and clears graded rows so the trust banner rebuilds from new picks only.
Pending predictions are kept. Run on the **worker** volume in split_v2 prod.

Usage:
  python scripts/reset_council_accuracy_epoch.py --dry-run
  python scripts/reset_council_accuracy_epoch.py --yes
  python scripts/reset_council_accuracy_epoch.py --yes --reset-weights
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

ARCHIVE_DIR = os.path.join("data", "predictions_archive")


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _archive_path(label: str) -> str:
    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    safe = label.replace(":", "-")
    return os.path.join(ARCHIVE_DIR, f"{safe}.json")


def reset_accuracy_epoch(
    *,
    dry_run: bool = True,
    reset_weights: bool = False,
    label: str | None = None,
) -> Dict[str, Any]:
    from internal.council.resolver import _compute_stats
    from internal.council.weights import DEFAULT_WEIGHTS, load_weights, save_weights
    from internal.learning.predictions_store import (
        PREDICTIONS_PATH,
        load_predictions,
        save_predictions,
        update_stats,
    )

    label = label or _utcnow()[:19].replace(":", "-")
    before = load_predictions()
    pending = list(before.get("predictions") or [])
    resolved = list(before.get("resolved") or [])
    stats_before = _compute_stats(before)

    archive_payload = {
        "archived_at": _utcnow(),
        "reason": "accuracy_epoch_reset",
        "label": label,
        "predictions": pending,
        "resolved": resolved,
        "stats": before.get("stats"),
        "resolver_stats": stats_before,
    }
    archive_file = _archive_path(f"pre-epoch-{label}")

    after: Dict[str, Any] = {
        "predictions": pending,
        "resolved": [],
        "stats": {"correct": 0, "wrong": 0, "pending": 0, "total": 0, "accuracy": 0.0},
        "accuracy_epoch": {
            "started_at": _utcnow(),
            "label": label,
            "archived_from": archive_file,
            "prior_graded": int(stats_before.get("correct", 0) or 0)
            + int(stats_before.get("wrong", 0) or 0),
            "prior_accuracy": stats_before.get("accuracy"),
        },
    }
    update_stats(after)

    weights_before = load_weights() if reset_weights else None
    weights_after = dict(DEFAULT_WEIGHTS) if reset_weights else None

    report = {
        "dry_run": dry_run,
        "archive_path": archive_file,
        "pending_kept": len(pending),
        "resolved_archived": len(resolved),
        "prior_stats": stats_before,
        "new_stats": _compute_stats(after),
        "predictions_path": PREDICTIONS_PATH,
        "reset_weights": reset_weights,
        "weights_before": weights_before,
        "weights_after": weights_after,
    }

    if dry_run:
        return report

    with open(archive_file, "w", encoding="utf-8") as handle:
        json.dump(archive_payload, handle, indent=2)
    save_predictions(after)

    if reset_weights and weights_after is not None:
        save_weights(weights_after)

    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Reset council accuracy epoch (archive + clear resolved).")
    parser.add_argument("--dry-run", action="store_true", help="Report only; do not write.")
    parser.add_argument("--yes", action="store_true", help="Apply changes (required to write).")
    parser.add_argument(
        "--reset-weights",
        action="store_true",
        help="Also reset expert council weights to 1.0 baseline in soul_map.json.",
    )
    parser.add_argument("--label", default=None, help="Archive filename label (default: UTC timestamp).")
    args = parser.parse_args()

    if not args.dry_run and not args.yes:
        print("Refusing to write without --yes (use --dry-run to preview).", file=sys.stderr)
        return 2

    report = reset_accuracy_epoch(
        dry_run=not args.yes,
        reset_weights=args.reset_weights,
        label=args.label,
    )
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
