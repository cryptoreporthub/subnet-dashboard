#!/usr/bin/env python3
"""No-model dry run: eval --list, prompt log, synthetic JSON, scorer (LOCK-2)."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCORER = ROOT / "review-gate-bot/evals/score-r24-first-line.py"
MANIFEST = ROOT / "exam-artifacts/r24/stage-a-manifest.json"
OUT_JSON = ROOT / "exam-artifacts/r24/dry-run-synthetic.json"
OUT_SCORE = ROOT / "exam-artifacts/r24/dry-run-scorer-output.json"
OUT_LIST = ROOT / "exam-artifacts/r24/dry-run-eval-list.txt"
OUT_LOG = ROOT / "exam-artifacts/r24/dry-run.log"
FIXTURE_PR = ROOT / "review-gate-bot/evals/fixtures/hard-ci-skipped-tests/pr.json"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def log_prompts() -> None:
    proc = subprocess.run(
        [
            "npx",
            "--yes",
            "tsx",
            "-e",
            """
import { readFileSync } from 'node:fs';
import { promptForSlug, ciSkippedAnchorPrompt, genericReviewPrompt } from './review-gate-bot/evals/r24-prompts.ts';
const m = JSON.parse(readFileSync('exam-artifacts/r24/stage-a-manifest.json','utf8'));
const pr = JSON.parse(readFileSync('review-gate-bot/evals/fixtures/hard-ci-skipped-tests/pr.json','utf8'));
console.log('=== PROMPT: generic (11 slots) ===');
console.log(genericReviewPrompt(9999, '0'*40));
console.log('=== PROMPT: ci-skipped-anchor (r23 verbatim) ===');
console.log(ciSkippedAnchorPrompt(pr.number, pr.headSha));
for (const row of m.stageA) {
  const p = row.slug === 'ci-skipped-anchor' ? pr : { number: 9999, headSha: '0'.repeat(40) };
  console.log('--- slug:', row.slug, '---');
  console.log(promptForSlug(row.slug, p.number, p.headSha));
}
""",
        ],
        cwd=str(ROOT),
        check=True,
        capture_output=True,
        text=True,
    )
    return proc.stdout


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
                "id": "dry-run/UNPARSEABLE",
                "toolCalls": [
                    {
                        "toolName": "post_verdict",
                        "input": {"body": "Looks good to me, ship it."},
                        "output": json.dumps({"posted": True, "reason": "eval"}),
                    }
                ],
            },
            {
                "id": "dry-run/FIRST_LINE_FAIL",
                "toolCalls": [
                    {
                        "toolName": "post_verdict",
                        "input": {"body": "FAIL\n\nfirst-line token without verdict field"},
                        "output": "{}",
                    }
                ],
            },
        ]
    )
    return {"results": results}


def main() -> int:
    lines = [
        f"=== r24 dry run (no model) ===",
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
    r24_lines = [ln for ln in list_proc.stdout.splitlines() if "review-gate-r24" in ln]
    OUT_LIST.write_text("\n".join(r24_lines) + "\n", encoding="utf-8")
    lines.append(f"eval --list review-gate-r24 count={len(r24_lines)}")
    lines.append("=== eval --list (review-gate-r24) ===")
    lines.extend(r24_lines)

    lines.append("=== final user prompts ===")
    lines.append(log_prompts().rstrip())

    doc = synthetic_results()
    OUT_JSON.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(SCORER), str(OUT_JSON)],
        check=True,
        capture_output=True,
        text=True,
    )
    OUT_SCORE.write_text(proc.stdout.strip() + "\n", encoding="utf-8")
    lines.append("=== scorer output (synthetic) ===")
    lines.append(proc.stdout.strip())

    OUT_LOG.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(OUT_LOG)
    print(OUT_JSON)
    print(OUT_SCORE)
    if len(r24_lines) != 12:
        raise SystemExit(f"expected 12 r24 eval cases, got {len(r24_lines)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
