#!/usr/bin/env python3
"""Build exam-artifacts/r25/sha256-manifest.json from r24 overlay + r25 harness files."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
R24_MANIFEST = ROOT / "exam-artifacts/r24/sha256-manifest.json"
OUT = ROOT / "exam-artifacts/r25/sha256-manifest.json"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    r24 = json.loads(R24_MANIFEST.read_text())
    out: dict[str, str] = {}
    for rel in r24:
        if rel.startswith("review-gate-bot/"):
            p = ROOT / rel
            if p.is_file():
                out[rel] = sha256_file(p)
    extra = [
        "review-gate-bot/evals/review-gate-r25.eval.ts",
        "review-gate-bot/evals/r25-prompts.ts",
        "exam-artifacts/r25/run-plan-c.json",
        "exam-artifacts/r25/stage-c-manifest.json",
        "exam-artifacts/r25/runs-c/README.md",
        "exam-artifacts/r25/dry-run-c-synthetic.json",
        "exam-artifacts/r25/dry-run-c-scorer-output.json",
        "exam-artifacts/r25/dry-run-c-eval-list.txt",
        "exam-artifacts/r25/dry-run-c.log",
        "exam-artifacts/r25/worktree-proof.log",
        "exam-artifacts/r25/worktree-model-config.log",
        "exam-artifacts/r25/fixture-execution-gate-output.txt",
        "exam-artifacts/r25/gate_fixture_python.py",
        "exam-artifacts/r25/r25c_dry_run.py",
        "exam-artifacts/r25/pin_manifest.py",
        "exam-artifacts/r25/pins.json",
        "review-gate-bot/evals/score-r24-first-line.py",
    ]
    for rel in extra:
        p = ROOT / rel
        if p.is_file():
            out[rel] = sha256_file(p)
    OUT.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(OUT, "keys", len(out))


if __name__ == "__main__":
    main()
