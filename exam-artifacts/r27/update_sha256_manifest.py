#!/usr/bin/env python3
"""Build exam-artifacts/r27/sha256-manifest.json from r25 overlay + r27 harness files."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
R25_MANIFEST = ROOT / "exam-artifacts/r25/sha256-manifest.json"
OUT = ROOT / "exam-artifacts/r27/sha256-manifest.json"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    r25 = json.loads(R25_MANIFEST.read_text())
    out: dict[str, str] = {}
    for rel in r25:
        if rel.startswith("review-gate-bot/"):
            p = ROOT / rel
            if p.is_file():
                out[rel] = sha256_file(p)
    extra = [
        "review-gate-bot/evals/review-gate-r27.eval.ts",
        "review-gate-bot/evals/r27-prompts.ts",
        "exam-artifacts/r27/run-plan-c.json",
        "exam-artifacts/r27/stage-c-manifest.json",
        "exam-artifacts/r27/runs-c/README.md",
        "exam-artifacts/r27/dry-run-c-synthetic.json",
        "exam-artifacts/r27/dry-run-c-scorer-output.json",
        "exam-artifacts/r27/dry-run-c-eval-list.txt",
        "exam-artifacts/r27/dry-run-c.log",
        "exam-artifacts/r27/worktree-proof.log",
        "exam-artifacts/r27/fixture-execution-gate-output.txt",
        "exam-artifacts/r27/gate_fixture_python.py",
        "exam-artifacts/r27/r27c_dry_run.py",
        "exam-artifacts/r27/pin_manifest.py",
        "exam-artifacts/r27/pins.json",
        "exam-artifacts/r27/build_r27_fixtures.py",
        "exam-artifacts/r27/gen_run_plan_c.py",
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
