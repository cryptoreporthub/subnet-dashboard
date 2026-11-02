#!/usr/bin/env python3
"""Refresh exam-artifacts/r24/sha256-manifest.json from disk."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = ROOT / "exam-artifacts/r24/sha256-manifest.json"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    existing = json.loads(MANIFEST_PATH.read_text())
    extra = [
        "review-gate-bot/evals/review-gate-r24.eval.ts",
        "review-gate-bot/evals/r24-prompts.ts",
        "exam-artifacts/r24/run-plan.json",
        "exam-artifacts/r24/dry-run-synthetic.json",
        "exam-artifacts/r24/dry-run-scorer-output.json",
        "exam-artifacts/r24/dry-run.log",
        "exam-artifacts/r24/dry-run-eval-list.txt",
        "exam-artifacts/r24/worktree-proof.log",
        "exam-artifacts/r24/worktree-model-config.log",
        "exam-artifacts/r24/runs/README.md",
    ]
    for rel in extra:
        p = ROOT / rel
        if p.is_file():
            existing[rel] = sha256_file(p)
    existing["exam-artifacts/r24/stage-a-manifest.json"] = sha256_file(ROOT / "exam-artifacts/r24/stage-a-manifest.json")
    existing["review-gate-bot/evals/score-r24-first-line.py"] = sha256_file(
        ROOT / "review-gate-bot/evals/score-r24-first-line.py"
    )
    MANIFEST_PATH.write_text(json.dumps(existing, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(MANIFEST_PATH)


if __name__ == "__main__":
    main()
