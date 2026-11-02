#!/usr/bin/env python3
"""Score Stage A invocation JSON files; attach pin from run-plan outputJson paths."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PLAN = ROOT / "exam-artifacts/r24/run-plan.json"
SCORER = ROOT / "review-gate-bot/evals/score-r24-first-line.py"


def main() -> int:
    plan = json.loads(PLAN.read_text())
    rows = []
    for block in plan["blocks"]:
        for inv in block["invocations"]:
            rel = inv["outputJson"]
            path = ROOT / rel
            pin = inv["pin"]
            if not path.is_file():
                rows.append({"path": rel, "pin": pin, "error": "missing"})
                continue
            proc = subprocess.run(
                [sys.executable, str(SCORER), str(path)],
                check=True,
                capture_output=True,
                text=True,
            )
            scored = json.loads(proc.stdout.strip())
            scored["pin"] = pin
            scored["invocationIndex"] = inv["invocationIndex"]
            rows.append(scored)
    print(json.dumps({"invocations": rows}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
