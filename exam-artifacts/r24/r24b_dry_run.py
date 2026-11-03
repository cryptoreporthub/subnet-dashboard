#!/usr/bin/env python3
"""No-model dry run for Stage B runner (RUN-READY-B)."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCORER = ROOT / "review-gate-bot/evals/score-r24-first-line.py"
MANIFEST = ROOT / "exam-artifacts/r24/stage-b-manifest.json"
OUT_JSON = ROOT / "exam-artifacts/r24/dry-run-b-synthetic.json"
OUT_SCORE = ROOT / "exam-artifacts/r24/dry-run-b-scorer-output.json"
OUT_LIST = ROOT / "exam-artifacts/r24/dry-run-b-eval-list.txt"
OUT_LOG = ROOT / "exam-artifacts/r24/dry-run-b.log"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def synthetic_results() -> dict:
    manifest = json.loads(MANIFEST.read_text())
    results = []
    for row in manifest["stageB"]:
        slug = row["slug"]
        results.append(
            {
                "id": f"review-gate-r24b/{slug}/1",
                "evalCase": f"review-gate-r24b/{slug}",
                "toolCalls": [
                    {
                        "toolName": "post_verdict",
                        "input": {"verdict": "MODIFY", "body": "MODIFY\n\nSynthetic Stage B dry-run."},
                        "output": json.dumps({"posted": True, "reason": "eval"}),
                    }
                ],
            }
        )
    return {"results": results}


def main() -> int:
    lines = [
        "=== r24 Stage B dry run (no model) ===",
        f"scorer={SCORER.relative_to(ROOT)} sha256={sha256_file(SCORER)}",
    ]
    manifest = json.loads(MANIFEST.read_text())
    if "contentPins" in manifest:
        lines.append(f"contentPins={json.dumps(manifest['contentPins'], sort_keys=True)}")

    list_proc = subprocess.run(
        ["npm", "run", "eval", "--", "--list"],
        cwd=str(ROOT / "review-gate-bot"),
        check=True,
        capture_output=True,
        text=True,
    )
    r24b_lines = [ln for ln in list_proc.stdout.splitlines() if "review-gate-r24b" in ln]
    OUT_LIST.write_text("\n".join(r24b_lines) + "\n", encoding="utf-8")
    lines.append(f"eval --list review-gate-r24b count={len(r24b_lines)}")
    lines.extend(r24b_lines)

    doc = synthetic_results()
    OUT_JSON.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(SCORER), str(OUT_JSON)],
        check=True,
        capture_output=True,
        text=True,
    )
    OUT_SCORE.write_text(proc.stdout.strip() + "\n", encoding="utf-8")
    lines.append("=== scorer output (synthetic MODIFY x12) ===")
    lines.append(proc.stdout.strip())

    OUT_LOG.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(OUT_LOG)
    if len(r24b_lines) != 12:
        raise SystemExit(f"expected 12 r24b cases, got {len(r24b_lines)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
