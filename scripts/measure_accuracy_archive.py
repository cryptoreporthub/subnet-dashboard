#!/usr/bin/env python3
"""Acc-1 — read-only archive accuracy measurement (pre-epoch corpus)."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

from internal.council.grading import direction_correct

NOISE_MAGNITUDE_PCT = 1.0


def _load_json(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    return data if isinstance(data, dict) else {"predictions": data, "resolved": []}


def load_archive(path: str) -> Dict[str, Any]:
    """Load archive file or merge all files under a pre-epoch directory."""
    if os.path.isfile(path):
        return _load_json(path)
    if not os.path.isdir(path):
        raise FileNotFoundError(path)

    merged: Dict[str, Any] = {"predictions": [], "resolved": []}
    names = sorted(
        entry
        for entry in os.listdir(path)
        if entry.startswith("pre-epoch-") and os.path.isfile(os.path.join(path, entry))
    )
    if not names:
        raise FileNotFoundError(f"no pre-epoch-* files in {path}")

    for name in names:
        blob = _load_json(os.path.join(path, name))
        merged["predictions"].extend(blob.get("predictions") or [])
        merged["resolved"].extend(blob.get("resolved") or [])
    merged["archive_files"] = names
    return merged


def iter_resolved(archive: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for bucket in ("resolved", "predictions"):
        for row in archive.get(bucket) or []:
            if not isinstance(row, dict):
                continue
            status = str(row.get("status") or "").lower()
            if bucket == "predictions" and status != "resolved":
                continue
            if row.get("actual_pct") is None and row.get("correct") is None:
                continue
            key = str(row.get("id") or f"{row.get('netuid')}-{row.get('created_at')}")
            if key in seen:
                continue
            seen.add(key)
            rows.append(row)
    return rows


def row_hit(row: Dict[str, Any]) -> Optional[bool]:
    if row.get("correct") is not None:
        return bool(row["correct"])
    outcome = str(row.get("outcome") or "").lower()
    if outcome == "hit":
        return True
    if outcome == "miss":
        return False
    actual = row.get("actual_pct")
    if actual is None:
        return None
    try:
        return direction_correct(row, float(actual))
    except (TypeError, ValueError):
        return None


def accuracy_stats(rows: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    graded: List[bool] = []
    for row in rows:
        hit = row_hit(row)
        if hit is not None:
            graded.append(hit)
    total = len(graded)
    correct = sum(1 for hit in graded if hit)
    return {
        "n": total,
        "correct": correct,
        "wrong": total - correct,
        "accuracy": round(correct / total, 4) if total else None,
    }


def _confidence(row: Dict[str, Any]) -> Optional[float]:
    for key in ("final_confidence", "pick_confidence", "confidence", "conviction"):
        raw = row.get(key)
        if raw is None:
            continue
        try:
            val = float(raw)
            return val / 100.0 if val > 1.0 else val
        except (TypeError, ValueError):
            continue
    return None


def _expert(row: Dict[str, Any]) -> str:
    expert = row.get("expert")
    if isinstance(expert, str) and expert:
        return expert
    experts = row.get("experts_involved")
    if isinstance(experts, list) and experts:
        return str(experts[0])
    return "unknown"


def confidence_deciles(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    buckets: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in rows:
        conf = _confidence(row)
        if conf is None:
            label = "unknown"
        elif conf < 0.35:
            label = "0-35%"
        elif conf < 0.45:
            label = "35-45%"
        elif conf < 0.55:
            label = "45-55%"
        elif conf < 0.70:
            label = "55-70%"
        else:
            label = "70%+"
        buckets[label].append(row)
    order = ["0-35%", "35-45%", "45-55%", "55-70%", "70%+", "unknown"]
    return [{"bucket": label, **accuracy_stats(buckets[label])} for label in order if buckets[label]]


def grouped_accuracy(rows: List[Dict[str, Any]], key_fn) -> List[Dict[str, Any]]:
    groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[str(key_fn(row) or "unknown")].append(row)
    out = []
    for label in sorted(groups, key=lambda k: (-len(groups[k]), k)):
        out.append({"label": label, **accuracy_stats(groups[label])})
    return out


def magnitude_noise_share(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    misses = []
    for row in rows:
        hit = row_hit(row)
        if hit is not False:
            continue
        try:
            actual = abs(float(row.get("actual_pct") or 0))
        except (TypeError, ValueError):
            actual = 0.0
        misses.append(actual)
    if not misses:
        return {"misses": 0, "small_move_misses": 0, "share": None}
    small = sum(1 for actual in misses if actual < NOISE_MAGNITUDE_PCT)
    return {
        "misses": len(misses),
        "small_move_misses": small,
        "share": round(small / len(misses), 4),
    }


def horizon_compare(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    by_hours = grouped_accuracy(rows, lambda r: int(r.get("horizon_hours") or 0))
    h4 = next((g for g in by_hours if g["label"] == "4"), None)
    h24 = next((g for g in by_hours if g["label"] == "24"), None)
    verdict = "inconclusive"
    if h4 and h24 and h4.get("accuracy") is not None and h24.get("accuracy") is not None:
        if h24["accuracy"] > h4["accuracy"] + 0.02:
            verdict = "24h_better"
        elif h4["accuracy"] > h24["accuracy"] + 0.02:
            verdict = "4h_better"
        else:
            verdict = "similar"
    return {"by_horizon_hours": by_hours, "verdict": verdict, "h4": h4, "h24": h24}


def build_summary(rows: List[Dict[str, Any]], archive_path: str) -> Dict[str, Any]:
    overall = accuracy_stats(rows)
    horizon = horizon_compare(rows)
    noise = magnitude_noise_share(rows)
    experts = grouped_accuracy(rows, _expert)
    net_negative = [e for e in experts if e.get("n", 0) >= 5 and (e.get("accuracy") or 0) < 0.5]
    return {
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "archive": archive_path,
        "overall": overall,
        "horizon_compare": horizon,
        "noise_misses": noise,
        "experts": experts,
        "net_negative_experts": net_negative,
        "confidence_deciles": confidence_deciles(rows),
        "pick_source": grouped_accuracy(rows, lambda r: r.get("pick_source") or r.get("signal_source") or "unknown"),
        "phase_at_prediction": grouped_accuracy(rows, lambda r: r.get("phase_at_prediction") or "unknown"),
    }


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
    recs = _recommendations(summary)
    for idx, rec in enumerate(recs, 1):
        lines.append(f"{idx}. {rec}")
    lines.append("")
    return "\n".join(lines)


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
