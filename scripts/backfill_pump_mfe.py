#!/usr/bin/env python3
"""P0.3 — backfill terminal_return_1h / mfe_max_1h on pump desk ledger rows.

Dry-run by default. Pass --apply to write. Never mutates signal_snapshot or
historical correct/outcome/actual_pct — only additive MFE fields.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Persist MFE fields (default is dry-run)",
    )
    parser.add_argument(
        "--report",
        action="store_true",
        help="Print terminal-only vs MFE hit-rate report after backfill compute",
    )
    parser.add_argument(
        "--predictions",
        default="data/predictions.json",
        help="Path to predictions.json",
    )
    parser.add_argument(
        "--price-cache",
        default=None,
        help="Optional price_cache path (defaults to module PRICE_CACHE_PATH)",
    )
    args = parser.parse_args(argv)

    from internal.file_utils import safe_read_json, safe_write_json
    from internal.learning.pump_mfe import backfill_pump_mfe, report_mfe_hit_rates

    path = Path(args.predictions)
    data = safe_read_json(str(path), default={})
    if not isinstance(data, dict):
        data = {}

    out, summary = backfill_pump_mfe(
        data,
        cache_path=args.price_cache,
        dry_run=not args.apply,
    )
    payload = {"summary": summary}
    if args.report:
        payload["hit_rates"] = report_mfe_hit_rates(out if args.apply else out)

    print(json.dumps(payload, indent=2, sort_keys=True))

    if args.apply and not summary.get("dry_run"):
        # Merge stamped resolved rows back into original structure
        data["resolved"] = out.get("resolved") or data.get("resolved") or []
        safe_write_json(str(path), data)
        print(f"wrote {path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
