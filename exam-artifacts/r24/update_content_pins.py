#!/usr/bin/env python3
"""Set stage-a-manifest.json contentPins (SHA-256 of frozen runner/scorer/plan files)."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = ROOT / "exam-artifacts/r24/stage-a-manifest.json"

PIN_PATHS = {
    "runPlan": ROOT / "exam-artifacts/r24/run-plan.json",
    "runPlanRerun": ROOT / "exam-artifacts/r24/run-plan-rerun.json",
    "runner": ROOT / "review-gate-bot/evals/review-gate-r24.eval.ts",
    "prompts": ROOT / "review-gate-bot/evals/r24-prompts.ts",
    "scorer": ROOT / "review-gate-bot/evals/score-r24-first-line.py",
}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def main() -> None:
    doc = json.loads(MANIFEST_PATH.read_text())
    doc.pop("harnessTip", None)
    doc.pop("runTip", None)
    doc.pop("contentPins", None)
    manifest_body = json.dumps(doc, indent=2, sort_keys=True) + "\n"
    pins = {
        "stageAManifest": sha256_bytes(manifest_body.encode()),
        "runPlan": sha256_file(PIN_PATHS["runPlan"]),
        "runPlanRerun": sha256_file(PIN_PATHS["runPlanRerun"]),
        "runner": sha256_file(PIN_PATHS["runner"]),
        "prompts": sha256_file(PIN_PATHS["prompts"]),
        "scorer": sha256_file(PIN_PATHS["scorer"]),
    }
    doc["contentPins"] = pins
    doc["runner"] = "review-gate-bot/evals/review-gate-r24.eval.ts"
    doc["prompts"] = "review-gate-bot/evals/r24-prompts.ts"
    MANIFEST_PATH.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(pins, indent=2))


if __name__ == "__main__":
    main()
