#!/usr/bin/env python3
"""No-model dry run: synthetic eval JSON through score-r24-first-line.py."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCORER = ROOT / "review-gate-bot/evals/score-r24-first-line.py"
MANIFEST = ROOT / "exam-artifacts/r24/stage-a-manifest.json"
OUT_JSON = ROOT / "exam-artifacts/r24/dry-run-synthetic.json"
OUT_SCORE = ROOT / "exam-artifacts/r24/dry-run-scorer-output.json"


def synthetic_results() -> dict:
    manifest = json.loads(MANIFEST.read_text())
    results = []
    for row in manifest["stageA"]:
        slug = row["slug"]
        oracle = row["oracle"]
        verdict = "PASS" if oracle == "PASS" else "MODIFY"
        results.append(
            {
                "id": f"review-gate-r24/{slug}/1",
                "evalCase": f"review-gate-r24/{slug}",
                "toolCalls": [
                    {
                        "toolName": "post_verdict",
                        "input": {"verdict": verdict, "body": f"{verdict}\n\nSynthetic dry-run slot."},
                        "output": json.dumps({"posted": True, "reason": "eval"}),
                    }
                ],
            }
        )
    # Extra rows exercise scorer edge categories (not stage-A slots).
    results.extend(
        [
            {"id": "dry-run/NO_POST", "toolCalls": []},
            {
                "id": "dry-run/MULTI_POST",
                "toolCalls": [
                    {"toolName": "post_verdict", "input": {"verdict": "PASS"}, "output": "{}"},
                    {"toolName": "post_verdict", "input": {"verdict": "MODIFY"}, "output": "{}"},
                ],
            },
            {
                "id": "dry-run/FIRST_LINE",
                "toolCalls": [
                    {
                        "toolName": "post_verdict",
                        "input": {"body": "FAIL\n\nbody token ignored when verdict set separately"},
                        "output": "{}",
                    }
                ],
            },
        ]
    )
    return {"results": results}


def main() -> int:
    doc = synthetic_results()
    OUT_JSON.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(SCORER), str(OUT_JSON)],
        check=True,
        capture_output=True,
        text=True,
    )
    OUT_SCORE.write_text(proc.stdout.strip() + "\n", encoding="utf-8")
    print(OUT_JSON)
    print(OUT_SCORE)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
