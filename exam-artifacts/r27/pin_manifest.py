#!/usr/bin/env python3
"""Merge stage-c-manifest metadata + contentPins (reproducible stageCManifest pin)."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "exam-artifacts/r27/stage-c-manifest.json"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def stage_c_manifest_body_pin(doc: dict) -> str:
    stripped = {k: v for k, v in doc.items() if k != "contentPins"}
    body = json.dumps(stripped, indent=2, sort_keys=True) + "\n"
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def main() -> None:
    doc = json.loads(MANIFEST.read_text())
    doc.setdefault(
        "runPlanBlockOrder",
        {
            "1": ["R23", "C25"],
            "2": ["C25", "R23"],
            "3": ["R23", "C25"],
            "4": ["C25", "R23"],
            "5": ["R23", "C25"],
        },
    )
    doc["outputDir"] = "exam-artifacts/r27/runs-c/"
    doc["runnerC"] = "review-gate-bot/evals/review-gate-r27.eval.ts"
    doc["runPlanC"] = "exam-artifacts/r27/run-plan-c.json"
    doc["scorer"] = "review-gate-bot/evals/score-r24-first-line.py"
    doc["prompts"] = "review-gate-bot/evals/r27-prompts.ts"
    doc["r23Pin"] = "a5819378e012cfe21b021bf2b6c5a52d5c4e2d7e"
    doc["c25Pin"] = "06269de964afc69bc81dd71156caa5bb2594bea1"
    doc["contentPins"] = {
        "stageCManifest": stage_c_manifest_body_pin(doc),
        "runPlanC": sha256_file(ROOT / "exam-artifacts/r27/run-plan-c.json"),
        "runnerC": sha256_file(ROOT / "review-gate-bot/evals/review-gate-r27.eval.ts"),
        "prompts": sha256_file(ROOT / "review-gate-bot/evals/r27-prompts.ts"),
        "scorer": sha256_file(ROOT / "review-gate-bot/evals/score-r24-first-line.py"),
    }
    MANIFEST.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    print("stageCManifest pin", doc["contentPins"]["stageCManifest"])


if __name__ == "__main__":
    main()
