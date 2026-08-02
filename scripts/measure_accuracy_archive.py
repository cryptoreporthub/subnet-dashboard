#!/usr/bin/env python3
"""Acc-1 — read-only archive accuracy measurement (pre-epoch corpus)."""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, List, Tuple

from internal.accuracy_lift.measure import (
    build_summary,
    iter_resolved,
    load_archive,
)

# Re-export for callers that import from this script path.
__all__ = [
    "build_summary",
    "iter_resolved",
    "load_archive",
    "measure_archive",
    "render_markdown",
]


def _recommendations(summary: Dict[str, Any]) -> List[str]:
    recs: List[str] = []
    verdict = (summary.get("horizon_compare") or {}).get("verdict")
    if verdict == "24h_better":
        recs.append("Acc-2 knob A — align day picks to 24h horizon (4h headline understates).")
    elif verdict == "4h_better":
        recs.append("Keep 4h day horizon — 24h sim would not improve headline accuracy.")
    noise_share = (summary.get("noise_misses") or {}).get("share")
    if noise_share is not None and noise_share >= 0.4:
        recs.append("Acc-2 knob C — add min_move_pct guard before direction miss counts.")
    neg = summary.get("net_negative_experts") or []
    if any(e.get("label") == "quant" for e in neg):
        recs.append("Acc-2 knob B — soft-reset quant weight floor (net-negative in epoch).")
    low = next((b for b in summary.get("confidence_deciles") or [] if b.get("bucket") == "0-35%"), None)
    if low and low.get("n", 0) >= 10 and (low.get("accuracy") or 1) < 0.35:
        recs.append("Acc-2 knob D — tighten publish gate for sub-35% confidence bucket.")
    if not recs:
        recs.append("No single knob dominates — hold Acc-2 until more graded rows in current epoch.")
    return recs[:3]


def render_markdown(summary: Dict[str, Any]) -> str:
    overall = summary["overall"]
    horizon = summary["horizon_compare"]
    noise = summary["noise_misses"]
    lines = [
        "# Acc-1 archive measurement",
        "",
        f"Generated: {summary['generated_at']}",
        f"Archive: `{summary['archive']}`",
        "",
        "## Headline",
        f"- Graded rows: **{overall['n']}**",
        f"- Direction accuracy: **{overall['accuracy']:.1%}**" if overall.get("accuracy") is not None else "- Direction accuracy: n/a",
        "",
        "## 4h vs 24h horizon",
    ]
    for row in horizon.get("by_horizon_hours") or []:
        acc = row.get("accuracy")
        acc_txt = f"{acc:.1%}" if acc is not None else "n/a"
        lines.append(f"- {row['label']}h: n={row['n']} · {acc_txt}")
    lines.extend(
        [
            f"- Verdict: **{horizon.get('verdict')}**",
            "",
            "## Expert breakdown",
        ]
    )
    for row in summary.get("experts") or []:
        acc = row.get("accuracy")
        acc_txt = f"{acc:.1%}" if acc is not None else "n/a"
        lines.append(f"- {row['label']}: n={row['n']} · {acc_txt}")
    neg = summary.get("net_negative_experts") or []
    lines.append(f"- Net-negative (n≥5, acc<50%): {', '.join(e['label'] for e in neg) or 'none'}")
    lines.extend(["", "## Confidence deciles"])
    for row in summary.get("confidence_deciles") or []:
        acc = row.get("accuracy")
        acc_txt = f"{acc:.1%}" if acc is not None else "n/a"
        lines.append(f"- {row['bucket']}: n={row['n']} · {acc_txt}")
    lines.extend(["", "## Pick source"])
    for row in summary.get("pick_source") or []:
        acc = row.get("accuracy")
        acc_txt = f"{acc:.1%}" if acc is not None else "n/a"
        lines.append(f"- {row['label']}: n={row['n']} · {acc_txt}")
    share = noise.get("share")
    share_txt = f"{share:.1%}" if share is not None else "n/a"
    lines.extend(
        [
            "",
            "## Magnitude noise (wrong-sign, |actual|<1%)",
            f"- Misses: {noise.get('misses', 0)}",
            f"- Small-move misses: {noise.get('small_move_misses', 0)}",
            f"- Share of misses: {share_txt}",
            "",
            "## Recommendations (top 3)",
        ]
    )
    for idx, rec in enumerate(_recommendations(summary), 1):
        lines.append(f"{idx}. {rec}")
    lines.append("")
    return "\n".join(lines)


def measure_archive(path: str) -> Tuple[Dict[str, Any], str]:
    archive = load_archive(path)
    rows = iter_resolved(archive)
    summary = build_summary(rows, path)
    return summary, render_markdown(summary)


def main() -> int:
    parser = argparse.ArgumentParser(description="Measure pre-epoch prediction archive accuracy")
    parser.add_argument(
        "--archive",
        default="data/predictions_archive",
        help="Archive file or directory with pre-epoch-* snapshots",
    )
    parser.add_argument(
        "--out-json",
        default="data/learning_outcomes/acc1_archive_summary.json",
        help="JSON summary output path",
    )
    parser.add_argument(
        "--out-md",
        default="cursor-agents-communication/acc1-report.md",
        help="Markdown report output path",
    )
    args = parser.parse_args()

    try:
        summary, report = measure_archive(args.archive)
    except FileNotFoundError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}), file=sys.stderr)
        return 1

    os.makedirs(os.path.dirname(args.out_json) or ".", exist_ok=True)
    os.makedirs(os.path.dirname(args.out_md) or ".", exist_ok=True)
    with open(args.out_json, "w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2)
    with open(args.out_md, "w", encoding="utf-8") as handle:
        handle.write(report)

    print(json.dumps({"ok": True, "n": summary["overall"]["n"], "out_json": args.out_json, "out_md": args.out_md}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
