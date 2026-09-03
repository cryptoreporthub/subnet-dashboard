"""Correlate Fly raw logs for Patch D ghost-write / lock-convoy attribution.

Anchor patterns per research/lock-convoy-ghost-write-audit.md §1–§2.
Read-only: stdin or file → markdown report. No production mutation.

Patch D follow-up (2026-09-03): extended anchors for the background
timeout/failure family observed in capture run 33711955980 —
learning-health 20s timeouts, homepage cache-warm join_timeout
failures, pump desk snapshot stage timeouts, and fast shell
learning-metrics failures. Previously these lines matched no anchor
and were silently dropped, yielding misleading ZERO HITS reports.
Scheduler+fail/timeout combos classify as scheduler_timeout_ceiling.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

TIMESTAMP_RE = re.compile(r"(20\d\d-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?Z)")

WORKER_ABANDONED_RE = re.compile(
    r"worker abandoned|daily pick tick timed out after (\d+)s",
    re.I,
)
GENERATION_BUMP_RE = re.compile(r"work_generation|generation bump|tick_generation", re.I)
TMC_LATENCY_RE = re.compile(
    r"(tmc|taomarketcap|_fetch_tmc|singleflight).{0,80}?(\d+(?:\.\d+)?)\s*s",
    re.I,
)
TMC_MS_RE = re.compile(r"(tmc|taomarketcap).{0,60}?(\d+(?:\.\d+)?)\s*ms", re.I)
CACHE_PERSIST_RE = re.compile(
    r"pick_score_cache|predictions\.json|write_scheduler_hold|save_predictions|persist",
    re.I,
)
TIMEOUT_CEILING_RE = re.compile(
    r"(90s|180s|480s|8s|5s|timeout after 90|cycle_timeout_180|write_timeout_480|join_timeout|timed out|failed|error|\d+(?:\.\d+)?s)",
    re.I,
)
SCHEDULER_NAME_RE = re.compile(
    r"score snapshot|score-snapshot|resolver lifecycle|daily pick|hour pick|pump ladder|prediction_resolver|learning-health|homepage cache warm|pump desk snapshot|fast shell",
    re.I,
)
THREAD_NAME_RE = re.compile(
    r"(daily-pick-work|daily-pick-tick|hour-pick-tick|dpick-score|score-snap-write|score-snap-tick)",
    re.I,
)
PROCESS_HINT_RE = re.compile(r"RUN_MODE=worker|inline worker|worker\.py", re.I)

GHOST_WRITE_WINDOW_SECONDS = 90
TMC_SLOW_SECONDS = 2.0


@dataclass
class Hit:
    line_no: int
    timestamp: Optional[datetime]
    pattern: str
    thread: Optional[str]
    process: str
    line: str
    context_before: List[str] = field(default_factory=list)
    context_after: List[str] = field(default_factory=list)


@dataclass
class GhostFlag:
    kind: str  # SUSPECT | CONFIRMED
    abandoned_at: datetime
    write_at: datetime
    abandoned_line: str
    write_line: str
    thread: Optional[str]


def _parse_ts(text: str) -> Optional[datetime]:
    m = TIMESTAMP_RE.search(text)
    if not m:
        return None
    try:
        return datetime.fromisoformat(m.group(1).replace("Z", "+00:00"))
    except ValueError:
        return None


def _infer_process(line: str) -> str:
    if PROCESS_HINT_RE.search(line):
        return "worker"
    if "uvicorn" in line.lower() or "GET /" in line:
        return "web"
    return "unknown"


def _infer_thread(line: str) -> Optional[str]:
    m = THREAD_NAME_RE.search(line)
    return m.group(1) if m else None


def _classify_line(line: str) -> Optional[str]:
    if WORKER_ABANDONED_RE.search(line):
        return "worker_abandoned"
    if GENERATION_BUMP_RE.search(line):
        return "generation_bump"
    if CACHE_PERSIST_RE.search(line):
        return "cache_or_predictions_write"
    if SCHEDULER_NAME_RE.search(line) and TIMEOUT_CEILING_RE.search(line):
        return "scheduler_timeout_ceiling"
    for m in TMC_MS_RE.finditer(line):
        try:
            if float(m.group(2)) > TMC_SLOW_SECONDS * 1000:
                return "tmc_slow_ms"
        except (TypeError, ValueError):
            pass
    for m in TMC_LATENCY_RE.finditer(line):
        try:
            if float(m.group(2)) > TMC_SLOW_SECONDS:
                return "tmc_slow_s"
        except (TypeError, ValueError):
            pass
    if THREAD_NAME_RE.search(line):
        return "thread_ident"
    return None


def correlate_lines(lines: List[str]) -> Tuple[List[Hit], List[GhostFlag]]:
    hits: List[Hit] = []
    abandoned_events: List[Tuple[datetime, str, Optional[str], int]] = []
    write_events: List[Tuple[datetime, str, Optional[str], int]] = []

    for i, raw in enumerate(lines):
        line = raw.rstrip("\n")
        if not line.strip():
            continue
        kind = _classify_line(line)
        if not kind:
            continue
        ts = _parse_ts(line)
        thread = _infer_thread(line)
        proc = _infer_process(line)
        before = [lines[j].rstrip("\n") for j in range(max(0, i - 2), i)]
        after = [lines[j].rstrip("\n") for j in range(i + 1, min(len(lines), i + 3))]
        hits.append(
            Hit(
                line_no=i + 1,
                timestamp=ts,
                pattern=kind,
                thread=thread,
                process=proc,
                line=line,
                context_before=before,
                context_after=after,
            )
        )
        if kind == "worker_abandoned" and ts:
            abandoned_events.append((ts, line, thread, i + 1))
        if kind == "cache_or_predictions_write" and ts:
            write_events.append((ts, line, thread, i + 1))

    flags: List[GhostFlag] = []
    for ab_ts, ab_line, ab_thread, _ in abandoned_events:
        for wr_ts, wr_line, wr_thread, _ in write_events:
            delta = (wr_ts - ab_ts).total_seconds()
            if delta <= 0 or delta < GHOST_WRITE_WINDOW_SECONDS:
                continue
            kind = "GHOST-WRITE-SUSPECT"
            if ab_thread and wr_thread and ab_thread == wr_thread:
                kind = "GHOST-WRITE-CONFIRMED"
            elif ab_thread and wr_thread and ab_thread in wr_line and wr_thread in ab_line:
                kind = "GHOST-WRITE-CONFIRMED"
            flags.append(
                GhostFlag(
                    kind=kind,
                    abandoned_at=ab_ts,
                    write_at=wr_ts,
                    abandoned_line=ab_line,
                    write_line=wr_line,
                    thread=ab_thread or wr_thread,
                )
            )
    return hits, flags


def format_report(
    hits: List[Hit],
    flags: List[GhostFlag],
    *,
    source: str,
    capture_mode: str,
) -> str:
    out: List[str] = [
        "# Patch D correlated log report",
        "",
        f"- **source:** `{source}`",
        f"- **capture_mode:** {capture_mode}",
        f"- **generated_at:** {datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')}",
        f"- **pattern_hits:** {len(hits)}",
        f"- **ghost_write_flags:** {len(flags)}",
        "",
    ]
    if not hits:
        out.extend(
            [
                "## ZERO HITS",
                "",
                "No anchor patterns matched. Extend capture window or arm Phase 2 instrumentation.",
                "",
            ]
        )
    else:
        out.append("## Pattern hits")
        out.append("")
        out.append("| timestamp | process | thread | pattern | line |")
        out.append("|-----------|---------|--------|---------|------|")
        for h in hits:
            ts = h.timestamp.isoformat().replace("+00:00", "Z") if h.timestamp else "—"
            out.append(
                f"| {ts} | {h.process} | {h.thread or '—'} | {h.pattern} | `{h.line[:120]}` |"
            )
        out.append("")
        for h in hits:
            out.append(f"### Hit L{h.line_no} — {h.pattern}")
            out.append("")
            for ctx in h.context_before:
                out.append(f"    {ctx}")
            out.append(f"**> {h.line}**")
            for ctx in h.context_after:
                out.append(f"    {ctx}")
            out.append("")

    if flags:
        out.append("## Ghost-write flags")
        out.append("")
        for f in flags:
            out.append(f"### {f.kind}")
            out.append(f"- abandoned: `{f.abandoned_at.isoformat().replace('+00:00', 'Z')}`")
            out.append(f"- write: `{f.write_at.isoformat().replace('+00:00', 'Z')}`")
            out.append(f"- delta_seconds: {(f.write_at - f.abandoned_at).total_seconds():.1f}")
            out.append(f"- thread: `{f.thread or 'unknown'}`")
            out.append(f"- abandoned_line: `{f.abandoned_line}`")
            out.append(f"- write_line: `{f.write_line}`")
            out.append("")

    return "\n".join(out)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Patch D Fly log correlator")
    parser.add_argument("raw_log", type=Path, help="Path to raw flyctl logs")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path("logs/correlated.md"),
        help="Markdown output path",
    )
    parser.add_argument(
        "--capture-mode",
        default="retro-buffer",
        help="Description of how logs were captured (for report header)",
    )
    args = parser.parse_args(argv)

    if not args.raw_log.is_file():
        print(f"PATCHD_CAPTURE_FAIL: raw log missing: {args.raw_log}", file=sys.stderr)
        return 2

    text = args.raw_log.read_text(encoding="utf-8", errors="replace")
    if not text.strip():
        print(f"PATCHD_CAPTURE_FAIL: raw log empty: {args.raw_log}", file=sys.stderr)
        return 2

    if "Error: failed to authenticate" in text or "401 Unauthorized" in text:
        print("PATCHD_CAPTURE_FAIL: flyctl auth error in log stream", file=sys.stderr)
        return 2

    lines = text.splitlines()
    hits, flags = correlate_lines(lines)
    report = format_report(
        hits,
        flags,
        source=str(args.raw_log),
        capture_mode=args.capture_mode,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(report, encoding="utf-8")
    print(f"patchd_correlate: hits={len(hits)} flags={len(flags)} -> {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
