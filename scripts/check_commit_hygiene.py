#!/usr/bin/env python3
"""Check the staged diff before commit: runtime files, scorer digest seed, model names.

Usage:
  python scripts/check_commit_hygiene.py                 check the staged index
  python scripts/check_commit_hygiene.py --message FILE
                              also check a commit message file

Exit 1 with one line per violation. Judges the index, not .gitignore, so a file
that is tracked or force-added is still caught.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path
from typing import Iterable, List, Optional

RUNTIME_PREFIXES = ("data/",)
RUNTIME_FILES = ("tests/.liveness_allowlist_prev.json",)
SCORER_FILES = (
    "internal/council/state_vector.py",
    "internal/council/weights.py",
    "internal/council/confidence_calibration.py",
    "internal/council/scoring_context.py",
)
SCORER_SEED = "data_seeds/score_snapshots.json"
PATH_TOKENS = re.compile(r"CLAUDE\.md|\.claude/\S*")
# Attribution lines the harness may append. The trailer names whichever model
# serves the session, so the family may vary; the rest of the line must match.
ATTRIBUTION_TRAILER = re.compile(
    r"Co-Authored-By: Claude (Haiku|Sonnet|Opus|Fable) \d+\.\d+ <noreply@anthropic\.com>"
)
ATTRIBUTION_PREFIXES = ("Claude-Session: https://claude.ai/code/",)
MODEL_NAME = re.compile(
    r"claude[- ](haiku|sonnet|opus|fable|instant)|claude-\d"
    r"|\b(haiku|sonnet|opus|fable|grok|gemini|gpt)[- ]?\d",
    re.IGNORECASE,
)


def violations(staged: Iterable[str], message: Optional[str] = None) -> List[str]:
    staged = sorted(set(staged))
    out: List[str] = []
    for path in staged:
        if path.startswith(RUNTIME_PREFIXES) or path in RUNTIME_FILES:
            out.append(f"runtime file staged: {path}")
    if any(p in SCORER_FILES for p in staged) and SCORER_SEED not in staged:
        out.append(
            f"scorer file staged without {SCORER_SEED} (digest seed must move with it)"
        )
    if message is not None:
        for n, line in enumerate(message.splitlines(), 1):
            if ATTRIBUTION_TRAILER.fullmatch(line.strip()) or line.startswith(
                ATTRIBUTION_PREFIXES
            ):
                continue
            prose = PATH_TOKENS.sub("", line)
            if MODEL_NAME.search(prose):
                out.append(f"model name in commit message line {n}: {line.strip()!r}")
    return out


def staged_paths(root: Path) -> List[str]:
    res = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMRD"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    )
    return [p for p in res.stdout.splitlines() if p]


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--message", type=Path, help="commit message file to check")
    parser.add_argument("--root", default=".", type=Path)
    args = parser.parse_args(argv)
    message = args.message.read_text(encoding="utf-8") if args.message else None
    problems = violations(staged_paths(args.root.resolve()), message)
    for p in problems:
        print(f"HYGIENE {p}")
    print(f"hygiene: {len(problems)} violation(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
