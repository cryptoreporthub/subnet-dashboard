#!/usr/bin/env python3
"""No-model dry run for Stage C runner (RUN-READY-C prep)."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCORER = ROOT / "review-gate-bot/evals/score-r24-first-line.py"
MANIFEST = ROOT / "exam-artifacts/r25/stage-c-manifest.json"
OUT_JSON = ROOT / "exam-artifacts/r25/dry-run-c-synthetic.json"
OUT_SCORE = ROOT / "exam-artifacts/r25/dry-run-c-scorer-output.json"
OUT_LIST = ROOT / "exam-artifacts/r25/dry-run-c-eval-list.txt"
OUT_LOG = ROOT / "exam-artifacts/r25/dry-run-c.log"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def synthetic_results() -> dict:
    manifest = json.loads(MANIFEST.read_text())
    results = []
    for row in manifest["fixtures"]:
        slug = row["slug"]
        verdict = row["oracle"]
        results.append(
            {
                "id": f"review-gate-r25/{slug}/1",
                "evalCase": f"review-gate-r25/{slug}",
                "toolCalls": [
                    {
                        "toolName": "post_verdict",
                        "input": {"verdict": verdict, "body": f"{verdict}\n\nSynthetic Stage C dry-run."},
                        "output": json.dumps({"posted": True, "reason": "eval"}),
                    }
                ],
            }
        )
    return {"results": results}


def main() -> int:
    lines = [
        "=== r25 Stage C dry run (no model) ===",
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
    r25_lines = [ln for ln in list_proc.stdout.splitlines() if "review-gate-r25" in ln]
    OUT_LIST.write_text("\n".join(r25_lines) + "\n", encoding="utf-8")
    lines.append(f"eval --list review-gate-r25 count={len(r25_lines)}")
    lines.extend(r25_lines)

    doc = synthetic_results()
    OUT_JSON.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(SCORER), str(OUT_JSON)],
        check=True,
        capture_output=True,
        text=True,
    )
    OUT_SCORE.write_text(proc.stdout.strip() + "\n", encoding="utf-8")
    lines.append("=== scorer output (synthetic oracle-aligned) ===")
    lines.append(proc.stdout.strip())

    OUT_LOG.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(OUT_LOG)
    if len(r25_lines) != 20:
        raise SystemExit(f"expected 20 r25 cases, got {len(r25_lines)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
