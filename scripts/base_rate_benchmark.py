#!/usr/bin/env python3
"""P0.2 — unconditional +2% within-1h base-rate benchmark (read-only).

Aggregation / measurement only. Defaults to printing JSON (+ optional
markdown). Pass ``--write PATH`` to persist the JSON report; without that
flag nothing is written.

Unfreeze significance bar (also embedded in JSON output):
  Wilson lower bound (95%) of the signal-conditioned +2%/1h hit rate
  strictly above the unconditional base-rate point estimate, with N >= 100.

Council 50.5% is always labeled:
  "Council 50.5% (terminal-graded; UNAUDITED for measurement bias)"
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--markdown",
        action="store_true",
        help="Also print markdown table to stdout after JSON",
    )
    parser.add_argument(
        "--write",
        metavar="PATH",
        default=None,
        help="Explicit flag to persist JSON report (default: no write)",
    )
    parser.add_argument(
        "--with-mfe-report",
        action="store_true",
        help="Dry-run pump MFE backfill --report and merge hit_rates into comparison",
    )
    parser.add_argument(
        "--price-cache",
        default=None,
        help="Optional price_cache.json path",
    )
    parser.add_argument(
        "--pattern-ledger",
        default=None,
        help="Optional pump_pattern_ledger.json path",
    )
    args = parser.parse_args(argv)

    from internal.file_utils import safe_read_json, safe_write_json
    from internal.learning.base_rate import (
        UNFREEZE_BAR_TEXT,
        build_base_rate_report,
        render_markdown,
    )

    price_cache = (
        safe_read_json(args.price_cache, default={}) if args.price_cache else None
    )
    pattern_ledger = (
        safe_read_json(args.pattern_ledger, default={})
        if args.pattern_ledger
        else None
    )

    mfe_hit_rates = None
    if args.with_mfe_report:
        from internal.learning.pump_mfe import backfill_pump_mfe, report_mfe_hit_rates

        preds = safe_read_json("data/predictions.json", default={})
        out, _summary = backfill_pump_mfe(
            preds if isinstance(preds, dict) else {},
            dry_run=True,
        )
        mfe_hit_rates = report_mfe_hit_rates(out)

    report = build_base_rate_report(
        price_cache=price_cache,
        pattern_ledger=pattern_ledger,
        mfe_hit_rates=mfe_hit_rates,
    )
    report["unfreeze_significance_bar_text"] = UNFREEZE_BAR_TEXT

    print(json.dumps(report, indent=2, sort_keys=True, default=str))
    if args.markdown:
        print()
        print(render_markdown(report))

    if args.write:
        path = Path(args.write)
        safe_write_json(str(path), report)
        print(f"wrote {path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
